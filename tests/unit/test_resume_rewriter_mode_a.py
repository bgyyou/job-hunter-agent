"""v3 M-rebuild-2: 模式 A 改写器测试

覆盖 prompt 锁死的硬边界（不编造数据 + 保留原数字 + 每段改写说明）+ LLM 失败降级。
"""
import pytest
import asyncio

from services.resume_rewriter import ResumeRewriter, RewriteResult


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class ModeAFakeLLM:
    """模式 A 测试用 LLM：默认返回基于输入构造的"诚实"改写，保留所有原数字。"""

    def __init__(self, response=None):
        self.response = response  # None → 自动从 user message 抽数字构造
        self.calls = []

    async def analyze(self, messages, max_tokens=4096, temperature=0.3,
                      use_cache=True, system_prompt=None):
        self.calls.append({"system_prompt": system_prompt, "messages": messages})
        if self.response is not None:
            return _FakeResp(self.response)
        # 自动模式：从 user message 抽取 "数字+单位" 段（如 "200 单" / "120 万"），塞进 rewritten
        user_text = ""
        for m in messages or []:
            content = getattr(m, "content", "") or ""
            user_text += content + "\n"
        import re
        numbers = re.findall(r"\d+(?:\.\d+)?\s*[万千%人单次个条]?", user_text)
        kept = "、".join(n.strip() for n in numbers[:5]) or "原数字"
        return _FakeResp({
            "rewrites": [
                {
                    "original": "原段落",
                    "rewritten": (
                        "按 JD 视角改写，对接目标能力词。"
                        f"保留原数字：{kept}。"
                    ),
                    "rewrite_reason": "对接 JD 能力词，保留原数字",
                    "warning": "",
                }
            ]
        })


class _FakeResp:
    def __init__(self, payload):
        import json
        self.content = json.dumps(payload, ensure_ascii=False)


class ModeAFailingLLM:
    """模拟 LLM 服务不可用。"""

    async def analyze(self, *args, **kwargs):
        raise RuntimeError("LLM 服务不可用")


class TestRewriteModeA:
    """模式 A：基于原简历视角切换 + 不编造数据。"""

    def test_no_llm_returns_fallback(self):
        """无 LLM 客户端 → 降级到原样返回 + warning，不静默失败。"""
        rw = ResumeRewriter(llm_client=None)
        original = {
            "experience": [
                {"company": "字节跳动", "title": "实习", "description": "做产品"}
            ]
        }
        result = _run(rw.rewrite_mode_a(original, {"title": "AI 产品经理"}))
        assert isinstance(result, RewriteResult)
        assert result.mode == "A"
        assert result.needs_user_review is True
        assert len(result.warnings) > 0
        # 降级时原 description 保留
        assert result.rewrites[0]["rewritten"] == "做产品"
        assert "LLM" in result.rewrites[0]["warning"]

    def test_llm_success_returns_normalized_rewrites(self):
        """LLM 正常返回 → 标准化每段（section / mode / warning 必填）。"""
        # 用 hardcoded response 测标准化逻辑
        rw = ResumeRewriter(llm_client=ModeAFakeLLM(
            response={
                "rewrites": [
                    {
                        "original": "在字节做产品",
                        "rewritten": "改写后：负责 AI 产品规划",
                        "rewrite_reason": "对接 AI 能力词",
                        "warning": "",
                    }
                ]
            }
        ))
        original = {
            "experience": [
                {"company": "字节跳动", "title": "实习", "description": "做产品"}
            ]
        }
        jd = {"title": "AI 产品经理", "company": "字节跳动"}
        result = _run(rw.rewrite_mode_a(original, jd))
        assert result.mode == "A"
        assert len(result.rewrites) == 1
        rw_seg = result.rewrites[0]
        # 必填字段：original / rewritten / rewrite_reason / warning / section / mode
        for k in ("original", "rewritten", "rewrite_reason", "warning", "section", "mode"):
            assert k in rw_seg, f"missing field: {k}"
        assert rw_seg["mode"] == "A"
        assert rw_seg["section"] == "experience"

    def test_llm_response_preserves_original_numbers(self):
        """改写后保留所有原数字（这是模式 A 硬规则 #2）。"""
        rw = ResumeRewriter(llm_client=ModeAFakeLLM())
        original = {
            "experience": [
                {
                    "company": "字节跳动",
                    "title": "PM",
                    "description": "促成 200 单成交，GMV 120 万",
                }
            ]
        }
        jd = {"title": "AI 产品经理"}
        result = _run(rw.rewrite_mode_a(original, jd))
        out_text = result.rewrites[0]["rewritten"]
        # 保留关键数字
        assert "200" in out_text
        assert "120" in out_text

    def test_llm_failure_falls_back_to_original(self):
        """LLM 抛异常时降级到原样 + warning，不抛到调用方。"""
        rw = ResumeRewriter(llm_client=ModeAFailingLLM())
        original = {
            "experience": [
                {"company": "X", "title": "Y", "description": "原描述"}
            ]
        }
        result = _run(rw.rewrite_mode_a(original, {"title": "PM"}))
        assert result.mode == "A"
        assert result.rewrites[0]["rewritten"] == "原描述"
        assert "LLM" in result.rewrites[0]["warning"]

    def test_system_prompt_locked_against_fabrication(self):
        """系统 prompt 包含"不编造"硬规则（防止后续被改坏）。"""
        from services.resume_rewriter_prompts import MODE_A_SYSTEM_PROMPT
        # 锁死的 6 条硬规则关键词
        must_have = [
            "绝对不能编造",
            "保留所有数字",
            "改写思路",
            "建议删除",
        ]
        for kw in must_have:
            assert kw in MODE_A_SYSTEM_PROMPT, (
                f"模式 A prompt 缺少硬规则关键词: {kw}"
            )

    def test_each_rewrite_has_rewrite_reason(self):
        """每段改写都必须有 rewrite_reason（不允许空）。"""
        rw = ResumeRewriter(llm_client=ModeAFakeLLM())
        original = {
            "experience": [
                {"company": "A", "title": "PM", "description": "x" * 50},
                {"company": "B", "title": "PM", "description": "y" * 50},
            ]
        }
        # LLM 返回 2 段
        rw.llm_client = ModeAFakeLLM(
            response={
                "rewrites": [
                    {
                        "original": "x" * 50,
                        "rewritten": "改写 1",
                        "rewrite_reason": "对接 AI 能力词",
                    },
                    {
                        "original": "y" * 50,
                        "rewritten": "改写 2",
                        "rewrite_reason": "对接销售能力词",
                    },
                ]
            }
        )
        result = _run(rw.rewrite_mode_a(original, {"title": "PM"}))
        for seg in result.rewrites:
            assert seg.get("rewrite_reason"), "每段必须有 rewrite_reason"

    def test_invalid_json_response_falls_back(self):
        """LLM 返回无法解析的 JSON → 降级。"""
        class BadJSONLLM:
            async def analyze(self, *a, **kw):
                from tools.llm import LLMResponse
                return LLMResponse(
                    content="这不是 JSON",
                    model="fake",
                    tokens_used=10,
                    finish_reason="stop",
                )

        rw = ResumeRewriter(llm_client=BadJSONLLM())
        original = {"experience": [{"description": "原内容"}]}
        result = _run(rw.rewrite_mode_a(original, {"title": "PM"}))
        assert result.mode == "A"
        assert result.rewrites[0]["rewritten"] == "原内容"
        assert result.rewrites[0]["warning"]

    def test_empty_experience_returns_empty_rewrites(self):
        """空 experience + 无 LLM → fallback 返回空 rewrites（不抛异常）。"""
        rw = ResumeRewriter(llm_client=None)
        result = _run(rw.rewrite_mode_a({}, {"title": "PM"}))
        assert result.mode == "A"
        assert result.rewrites == []
        assert len(result.warnings) > 0  # fallback 总带 warning