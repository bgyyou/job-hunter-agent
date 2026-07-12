"""v3 M-rebuild-2: 模式 B 模板生成测试

覆盖 prompt 锁死的硬边界（不编公司名/学校/时间 + 数字用区间 + [AI 模板生成] 标注
+ anchored_keywords 非空）+ LLM 失败降级。
"""
import pytest
import asyncio

from services.resume_rewriter import ResumeRewriter, RewriteResult


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# 模式 B 必须"绝不出现"的具体公司名 / 学校名黑名单
FORBIDDEN_COMPANIES = [
    "字节跳动", "阿里巴巴", "腾讯", "美团", "百度", "京东", "小米", "华为",
    "滴滴", "快手", "小红书", "拼多多", "网易", "新浪",
]
FORBIDDEN_SCHOOLS = ["清华", "北大", "复旦", "交大", "浙大"]


class ModeBFakeLLM:
    """模式 B 测试用 LLM：返回符合硬规则的模板（数字用区间 + 标注 + 无公司名）。"""

    def __init__(self, response=None):
        self.response = response or {
            "templates": [
                {
                    "section": "experience",
                    "content": (
                        "在某互联网公司负责 AI 产品规划（数字用区间：月均促成 200-500 单成交），"
                        "协调研发团队完成 3-5 个项目上线。"
                    ),
                    "anchored_keywords": ["AI Agent 产品规划", "跨部门协调"],
                    "is_ai_generated": True,
                },
                {
                    "section": "projects",
                    "content": (
                        "作为 AI 项目 PM，负责 prompt 工程平台设计，月均服务 1000-2000 用户，"
                        "对接 JD 中的「产品规划」能力。"
                    ),
                    "anchored_keywords": ["产品规划"],
                    "is_ai_generated": True,
                },
            ]
        }
        self.calls = []

    async def analyze(self, messages, max_tokens=4096, temperature=0.5,
                      use_cache=True, system_prompt=None):
        from tools.llm import LLMResponse
        self.calls.append({"system_prompt": system_prompt})
        import json
        return _FakeResp(self.response)


class _FakeResp:
    def __init__(self, payload):
        import json
        self.content = json.dumps(payload, ensure_ascii=False)


class ModeBFailingLLM:
    async def analyze(self, *args, **kwargs):
        raise RuntimeError("LLM 502")


class TestRewriteModeB:
    """模式 B：生成无公司名/时间/学校的模板，数字用区间。"""

    def test_no_llm_returns_placeholder(self):
        """无 LLM 客户端 → 占位模板 + warning。"""
        rw = ResumeRewriter(llm_client=None)
        jd = {"title": "AI 产品经理"}
        result = _run(rw.rewrite_mode_b(jd, sections_to_generate=["experience"]))
        assert isinstance(result, RewriteResult)
        assert result.mode == "B"
        assert len(result.rewrites) == 1
        seg = result.rewrites[0]
        # 占位模板必须带 [AI 模板生成]
        assert "[AI 模板生成]" in seg["rewritten"]
        assert seg["is_ai_generated"] is True
        assert seg["warning"]

    def test_llm_success_returns_templates(self):
        """LLM 正常返回 → 标准化为 rewrites 格式。"""
        rw = ResumeRewriter(llm_client=ModeBFakeLLM())
        jd = {"title": "AI 产品经理", "industry": "互联网", "function": "产品"}
        result = _run(rw.rewrite_mode_b(jd))
        assert result.mode == "B"
        assert len(result.rewrites) == 2
        for seg in result.rewrites:
            assert seg["mode"] == "B"
            assert seg["is_ai_generated"] is True
            # anchored_keywords 必填（来自 JD）
            assert isinstance(seg["anchored_keywords"], list)

    def test_no_specific_company_names_in_output(self):
        """模式 B 输出不得含具体公司名（prompt 硬规则 #1）。"""
        rw = ResumeRewriter(llm_client=ModeBFakeLLM())
        jd = {"title": "AI 产品经理"}
        result = _run(rw.rewrite_mode_b(jd))
        all_text = " ".join(seg["rewritten"] for seg in result.rewrites)
        for company in FORBIDDEN_COMPANIES:
            assert company not in all_text, (
                f"模式 B 输出含具体公司名: {company}"
            )

    def test_no_specific_school_names_in_output(self):
        """模式 B 输出不得含具体学校名。"""
        rw = ResumeRewriter(llm_client=ModeBFakeLLM())
        result = _run(rw.rewrite_mode_b({"title": "PM"}))
        all_text = " ".join(seg["rewritten"] for seg in result.rewrites)
        for school in FORBIDDEN_SCHOOLS:
            assert school not in all_text, (
                f"模式 B 输出含具体学校名: {school}"
            )

    def test_ai_tag_appended_even_if_llm_omits(self):
        """即使 LLM 返回内容没带 [AI 模板生成]，代码也会强制追加。"""
        rw = ResumeRewriter(
            llm_client=ModeBFakeLLM(
                response={
                    "templates": [
                        {
                            "section": "experience",
                            "content": "负责 AI 产品规划",  # 故意没标注
                            "anchored_keywords": ["AI"],
                        }
                    ]
                }
            )
        )
        result = _run(rw.rewrite_mode_b({"title": "PM"}))
        content = result.rewrites[0]["rewritten"]
        assert "[AI 模板生成]" in content

    def test_anchored_keywords_not_empty(self):
        """每段模板都必须有 anchored_keywords（对接 JD 能力词）。"""
        rw = ResumeRewriter(llm_client=ModeBFakeLLM())
        result = _run(rw.rewrite_mode_b({"title": "PM"}))
        for seg in result.rewrites:
            assert seg["anchored_keywords"], "每段必须有 anchored_keywords"
            assert all(isinstance(k, str) for k in seg["anchored_keywords"])

    def test_system_prompt_locked(self):
        """系统 prompt 锁死的 5 条硬规则。"""
        from services.resume_rewriter_prompts import MODE_B_SYSTEM_PROMPT
        must_have = [
            "编造",   # 匹配"绝对不能编造公司名"
            "AI 模板生成",
            "数字用范围",
            "公司名",
        ]
        text = MODE_B_SYSTEM_PROMPT
        for kw in must_have:
            assert kw in text, f"模式 B prompt 缺少硬规则关键词: {kw}"

    def test_llm_failure_returns_placeholder(self):
        """LLM 失败时降级到占位模板，不抛异常。"""
        rw = ResumeRewriter(llm_client=ModeBFailingLLM())
        result = _run(rw.rewrite_mode_b({"title": "PM"}, sections_to_generate=["experience"]))
        assert result.mode == "B"
        assert len(result.rewrites) == 1
        assert "[AI 模板生成]" in result.rewrites[0]["rewritten"]
        assert result.rewrites[0]["warning"]

    def test_invalid_json_falls_back(self):
        """LLM 返回坏 JSON → 占位模板。"""
        class BadLLM:
            async def analyze(self, *a, **kw):
                from tools.llm import LLMResponse
                return LLMResponse(
                    content="无 JSON",
                    model="fake",
                    tokens_used=5,
                    finish_reason="stop",
                )

        rw = ResumeRewriter(llm_client=BadLLM())
        result = _run(rw.rewrite_mode_b({"title": "PM"}, sections_to_generate=["experience"]))
        assert result.mode == "B"
        assert "[占位模板" in result.rewrites[0]["rewritten"]

    def test_rewrites_preserve_section_field(self):
        """改写后的 section 字段保留（experience / projects / achievements）。"""
        rw = ResumeRewriter(llm_client=ModeBFakeLLM())
        result = _run(rw.rewrite_mode_b({"title": "PM"}))
        sections = [seg["section"] for seg in result.rewrites]
        assert "experience" in sections
        assert "projects" in sections