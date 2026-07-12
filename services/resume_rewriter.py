"""v3 M-rebuild-2: 简历改写服务

按 update_plan.md §2.4 锁死的 prompt 约束：
- 模式 A：基于原简历视角切换，保留所有数字/人名/时间
- 模式 B：生成无公司名/时间/学校的模板，数字用区间
- 模式 A+B：已有段落按 A 改写 + 缺失段落按 B 补全
- auto：根据信息量评分（Phase 2c）自动选 A / A+B / B

每个 rewrite 段都包含：
- section / mode / original / rewritten / rewrite_reason / warning
- 模式 B 还含 anchored_keywords（对接 JD 能力词）+ is_ai_generated

**LLM 客户端可注入**（provider-neutral，沿用 tools/llm.LLMClient）。
无 LLM 时降级到"原样返回 + warning"，不静默失败。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

from loguru import logger

from services.resume_rewriter_prompts import (
    MODE_A_SYSTEM_PROMPT,
    MODE_B_SYSTEM_PROMPT,
    MODE_AB_SYSTEM_PROMPT,
    build_mode_a_user_prompt,
    build_mode_b_user_prompt,
)


RewriteMode = Literal["A", "B", "A+B", "auto"]


@dataclass
class RewriteResult:
    """改写结果（含每段详情 + 改写说明）。"""

    mode: str                              # "A" / "B" / "A+B"
    rewrites: List[Dict[str, Any]] = field(default_factory=list)
    needs_user_review: bool = True         # 改写结果始终需要用户校对
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "rewrites": self.rewrites,
            "needs_user_review": self.needs_user_review,
            "warnings": self.warnings,
        }


# ============================================================
# Duck-type 辅助：dict / ResumeProfile / StructuredJD 都可访问
# ============================================================

def _to_dict(obj: Any) -> Dict[str, Any]:
    """把 ResumeProfile / StructuredJD 等转 dict（用于 prompt 构造）。"""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "to_db_dict"):
        return obj.to_db_dict()  # StructuredJD
    if hasattr(obj, "model_dump"):
        return obj.model_dump()  # Pydantic
    if hasattr(obj, "__dict__"):
        return vars(obj)
    return {}


def _strip_code_fence(text: str) -> str:
    """剥离 LLM 返回的 markdown code fence。"""
    if not text:
        return text or ""
    text = text.strip()
    if text.startswith("```"):
        # 去掉开头 ```json 或 ```
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


# ============================================================
# ResumeRewriter
# ============================================================

class ResumeRewriter:
    """v3 简历改写器：模式 A / B / A+B / auto 四种入口。"""

    def __init__(self, llm_client: Optional[Any] = None, scorer: Optional[Any] = None):
        self.llm_client = llm_client
        self.scorer = scorer  # Phase 2c: InformationScorer

    async def rewrite_mode_a(self, original: Any, jd: Any) -> RewriteResult:
        """模式 A：基于原简历改写（不编造数据）。"""
        original_d = _to_dict(original)
        jd_d = _to_dict(jd)

        if self.llm_client is None:
            return self._fallback_mode_a(original_d, jd_d, reason="LLM 客户端未配置")

        try:
            from tools.llm import LLMMessage  # type: ignore
        except ImportError:
            return self._fallback_mode_a(original_d, jd_d, reason="tools.llm 未加载")

        user_prompt = build_mode_a_user_prompt(original_d, jd_d)
        messages = [LLMMessage(role="user", content=user_prompt)]
        try:
            response = await self.llm_client.analyze(
                messages=messages,
                system_prompt=MODE_A_SYSTEM_PROMPT,
                max_tokens=4096,
                temperature=0.3,
                use_cache=True,
            )
        except Exception as e:
            return self._fallback_mode_a(original_d, jd_d, reason=f"LLM 调用失败: {e!s}"[:200])
        raw = _strip_code_fence(response.content or "")
        parsed = self._safe_json_loads(raw)
        rewrites = parsed.get("rewrites") if isinstance(parsed, dict) else None

        if not isinstance(rewrites, list) or not rewrites:
            return self._fallback_mode_a(
                original_d, jd_d, reason=f"LLM 返回无法解析: {raw[:120]}"
            )

        # 标准化 + 给每段加 section 标记
        for i, rw in enumerate(rewrites):
            rw.setdefault("section", self._guess_section(rw, original_d, i))
            rw.setdefault("mode", "A")
            rw.setdefault("warning", "")

        return RewriteResult(
            mode="A",
            rewrites=rewrites,
            warnings=[],
        )

    async def rewrite_mode_b(
        self,
        jd: Any,
        sections_to_generate: Optional[List[str]] = None,
    ) -> RewriteResult:
        """模式 B：生成无公司名/时间/学校的模板。"""
        sections = sections_to_generate or ["experience", "projects"]
        jd_d = _to_dict(jd)

        if self.llm_client is None:
            return self._fallback_mode_b(jd_d, sections, reason="LLM 客户端未配置")

        try:
            from tools.llm import LLMMessage  # type: ignore
        except ImportError:
            return self._fallback_mode_b(jd_d, sections, reason="tools.llm 未加载")

        user_prompt = build_mode_b_user_prompt(jd_d, sections)
        messages = [LLMMessage(role="user", content=user_prompt)]
        try:
            response = await self.llm_client.analyze(
                messages=messages,
                system_prompt=MODE_B_SYSTEM_PROMPT,
                max_tokens=4096,
                temperature=0.5,
                use_cache=True,
            )
        except Exception as e:
            return self._fallback_mode_b(jd_d, sections, reason=f"LLM 调用失败: {e!s}"[:200])
        raw = _strip_code_fence(response.content or "")
        parsed = self._safe_json_loads(raw)
        templates = parsed.get("templates") if isinstance(parsed, dict) else None

        if not isinstance(templates, list) or not templates:
            return self._fallback_mode_b(
                jd_d, sections, reason=f"LLM 返回无法解析: {raw[:120]}"
            )

        for tpl in templates:
            tpl.setdefault("is_ai_generated", True)
            tpl.setdefault("anchored_keywords", [])
            tpl.setdefault("warning", "")
            # 模式 B 强制末尾 [AI 模板生成] 标注
            content = tpl.get("content", "")
            if content and "[AI 模板生成]" not in content:
                tpl["content"] = content.rstrip() + " [AI 模板生成]"

        # 统一为 rewrites 格式
        rewrites = [
            {
                "section": tpl.get("section", "experience"),
                "mode": "B",
                "original": None,
                "rewritten": tpl.get("content", ""),
                "rewrite_reason": "AI 模板生成（无公司名/时间）",
                "anchored_keywords": tpl.get("anchored_keywords", []),
                "warning": tpl.get("warning", ""),
                "is_ai_generated": True,
            }
            for tpl in templates
        ]
        return RewriteResult(mode="B", rewrites=rewrites, warnings=[])

    async def rewrite(
        self,
        original: Any,
        jd: Any,
        mode: RewriteMode = "auto",
    ) -> RewriteResult:
        """统一入口。

        - mode="auto"：调 InformationScorer 自动选 A / A+B / B
        - mode="A" / "B"：直接调对应实现
        - mode="A+B"：先跑 A，再补 B（覆盖空段）
        """
        if mode == "auto":
            if self.scorer is None:
                # 没 scorer 时 fallback 到模式 A
                logger.warning("[ResumeRewriter] mode=auto 但未注入 scorer，降级到模式 A")
                mode = "A"
            else:
                original_d = _to_dict(original)
                score = self.scorer.score(original_d)
                mode = score.recommended_mode  # "A" / "A+B" / "B"
                logger.info(f"[ResumeRewriter] auto → mode={mode} (score={score.total_score})")

        if mode == "A":
            return await self.rewrite_mode_a(original, jd)
        if mode == "B":
            return await self.rewrite_mode_b(jd)
        if mode == "A+B":
            result_a = await self.rewrite_mode_a(original, jd)
            # 找空段（没数据的段）用模式 B 补全
            original_d = _to_dict(original)
            empty_sections = self._detect_empty_sections(original_d)
            if empty_sections:
                result_b = await self.rewrite_mode_b(jd, sections_to_generate=empty_sections)
                # 合并 rewrites
                combined_rewrites = (result_a.rewrites or []) + (result_b.rewrites or [])
                return RewriteResult(
                    mode="A+B",
                    rewrites=combined_rewrites,
                    warnings=result_a.warnings + result_b.warnings,
                )
            return result_a

        raise ValueError(f"Unknown rewrite mode: {mode!r}（应为 A/B/A+B/auto）")

    # ---------------- helpers ----------------

    @staticmethod
    def _safe_json_loads(text: str) -> Dict[str, Any]:
        """JSON 解析（容错）。"""
        import json
        if not text:
            return {}
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            pass
        # 尝试从文本中抽取 {...}
        import re
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                return json.loads(m.group(0))
            except (json.JSONDecodeError, TypeError):
                pass
        return {}

    @staticmethod
    def _guess_section(rewrite: Dict[str, Any], original: Dict[str, Any], idx: int) -> str:
        """从原简历段推断 section 名（experience/projects/education/achievements）。"""
        original_text = (rewrite.get("original") or "").lower()
        experience = original.get("experience") or []
        projects = original.get("projects") or []
        achievements = original.get("achievements") or []
        # 按顺序匹配
        if idx < len(experience):
            return "experience"
        if idx < len(experience) + len(projects):
            return "projects"
        if idx < len(experience) + len(projects) + len(achievements):
            return "achievements"
        return "experience"

    @staticmethod
    def _detect_empty_sections(original: Dict[str, Any]) -> List[str]:
        """检测信息量为空的段（无公司名/无项目名/无独立成果）。"""
        empty: List[str] = []
        experience = original.get("experience") or []
        has_meaningful_exp = any(
            isinstance(e, dict) and (e.get("company") or e.get("description"))
            for e in experience
        )
        if not has_meaningful_exp:
            empty.append("experience")

        projects = original.get("projects") or []
        has_meaningful_proj = any(
            isinstance(p, dict) and (p.get("name") or p.get("description"))
            for p in projects
        )
        if not has_meaningful_proj:
            empty.append("projects")

        achievements = original.get("achievements") or []
        if not achievements:
            empty.append("achievements")

        return empty

    @staticmethod
    def _fallback_mode_a(original: Dict[str, Any], jd: Dict[str, Any],
                         reason: str) -> RewriteResult:
        """LLM 不可用时的降级实现：原样返回 + warning。"""
        rewrites: List[Dict[str, Any]] = []
        experience = original.get("experience") or []
        for i, exp in enumerate(experience):
            if isinstance(exp, dict):
                rewrites.append({
                    "section": "experience",
                    "mode": "A",
                    "original": exp.get("description", ""),
                    "rewritten": exp.get("description", ""),
                    "rewrite_reason": "LLM 不可用，原样返回（请人工校对）",
                    "warning": reason,
                })
        return RewriteResult(
            mode="A",
            rewrites=rewrites,
            warnings=[reason],
            needs_user_review=True,
        )

    @staticmethod
    def _fallback_mode_b(jd: Dict[str, Any], sections: List[str],
                         reason: str) -> RewriteResult:
        """LLM 不可用时的模式 B 降级：返回占位 + warning。"""
        rewrites = [
            {
                "section": s,
                "mode": "B",
                "original": None,
                "rewritten": (
                    f"[占位模板：{s}] 请结合自身情况填写 — 描述你在这段经历中做的事 + "
                    f"对接 {jd.get('title') or '目标岗位'} 的能力词（数字用区间） [AI 模板生成]"
                ),
                "rewrite_reason": "LLM 不可用，返回占位模板",
                "anchored_keywords": [],
                "warning": reason,
                "is_ai_generated": True,
            }
            for s in sections
        ]
        return RewriteResult(
            mode="B",
            rewrites=rewrites,
            warnings=[reason],
            needs_user_review=True,
        )