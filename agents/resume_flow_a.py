# -*- coding: utf-8 -*-
"""
Flow A: 0→1 对话式简历生成 Agent

流程：
  行业选择 → 岗位选择 → section 状态机分段采集 → 派生 summary/能力 → RAG 骨架 → 渲染

按 SECTIONS 顺序采集 8 段（6 个 chat 采集 + 2 个 LLM 派生），每段独立完成。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from loguru import logger

from tools.generator.resume_generator import ResumeGenerator
from tools.llm import LLMMessage, LLMResponse


# ----------------------------------------------------------------
# Section 状态机 — 分段采集，每段聚焦、独立小结
# ----------------------------------------------------------------

_SECTION_CHAT_SYSTEM = """你是简历助手，正在采集**{section_name}**这一段信息。专注本段，不要跑题问其他段。

【本段任务】
{section_task}

【本段必填项】
{section_must_have}

【对话规则】
1. 每轮只问 1-2 个问题，不要一次性列出长清单
2. 用户说"跳过""不适用""没有"算回答了，不要纠缠
3. 该段所有必填项都问到（用户答了/明确跳过）后，在回复末尾加 [SECTION_DONE]
4. 用户明确说"这段全跳过"时，回复一句确认后输出 [SECTION_DONE,SKIP]
5. 你最多可以问 {max_rounds} 轮；接近上限时果断收尾
6. 已采集段里有多个项目/经历时，如果用户已说过角色相同，后续条目不要重复问角色

【已采集的其他段（仅供参考，避免重复问）】
{collected_summary}

【目标岗位上下文】
行业：{industry}    岗位：{position}"""

_SECTION_EXTRACT_SYSTEM = """你是简历数据提取专家。从对话历史中只提取**{section_name}**这一段的结构化数据。

【输出 JSON 字段】
{section_schema}

要求：
1. 只提取用户明确说过的，不要编造；缺失字段留空字符串或空列表
2. 不要把其他段的内容（如工作经历）塞进本段
3. 用户口语描述保留原意，仅做轻微润色

只返回 JSON，不要其他文字。"""

_DERIVE_SYSTEM = """你是资深简历优化专家。基于已采集的简历数据，派生**个人总结**和**核心能力**两个字段。

【绝对禁令】
1. **禁止占位符**：不准 `[您的姓名]`、`[X]年`、`xxx`、`待补充` 等
2. **禁止编造**：用户没提到的数据不准发明；信息不足时写得概括一点，不要写具体数字
3. **必须基于真实数据**：summary 1-2 句话，core_competencies 3-5 条 bullet，全部来自已采集的内容

【目标岗位上下文】
行业：{industry}    岗位：{position}

【目标岗位核心要求（来自 JD 库蒸馏）】
{skeleton_block}

派生原则：core_competencies **优先**选用与上述岗位核心要求**有真实证据支撑**的技能/经验角度来组织表述（用户简历里有的内容，用岗位要求的视角包装）；summary 写法朝岗位要求靠拢。**严禁**把用户没做过的岗位要求点编造成核心能力。

返回 JSON：
{{
    "summary": "1-2 句个人总结",
    "core_competencies": ["核心能力 1", "核心能力 2", "..."]
}}

只返回 JSON，不要其他文字。"""


_REWRITE_EXPERIENCE_SYSTEM = """你是资深简历优化专家，正在帮用户把工作经历改写得**与目标岗位更相关**。

【目标岗位上下文】
行业：{industry}    岗位：{position}

【目标岗位核心要求（来自 JD 库蒸馏）】
{skeleton_block}

【改写原则】
1. **事实不变，视角重构**：用户做过的事不能编造，但要挖掘与目标岗位可迁移的能力维度
2. **突出可迁移技能**：把不相关经历的成果，转译成目标岗位关心的能力证据
   - 销售/客服 → 客户需求洞察、数据驱动运营、跨文化沟通、客户留存
   - 行政/运营 → 跨部门协同、流程优化、项目交付、资源协调
   - 教师/培训 → 知识传递、用户教育、内容设计、影响他人
3. **量化保留**：用户给的数字（续保率、满意度、客户数）保留，但重新框定为岗位相关指标
4. **语言贴近岗位**：用目标岗位 JD 的高频词替换原表达，但不要堆砌术语
5. **避免造假**：不编造用户没提过的职责；不确定的领域写得概括一点

【输入】用户原始经历条目（JSON）。
【输出】改写后的经历条目（JSON），保持字段结构，只改 description 和 achievements 内容。
保持 achievements 是 list[str]，description 是 str。

只返回 JSON，不要其他文字。"""


_REWRITE_PROJECTS_SYSTEM = """你是资深简历优化专家，正在帮用户把项目经历改写得**与目标岗位更相关**。

【目标岗位上下文】
行业：{industry}    岗位：{position}

【目标岗位核心要求（来自 JD 库蒸馏）】
{skeleton_block}

【改写原则】
1. **保留技术栈和角色**：tech_stack 和 role 原样保留，只改 description 和 achievements
2. **突出岗位相关能力**：项目里与目标岗位无关的细节弱化，相关维度放大
3. **量化成果贴近岗位**：把项目成果重新表述成目标岗位关心的指标（效率提升、用户增长、成本节约、质量提升）
4. **避免堆砌**：不要把 JD 关键词生硬塞进去，要自然融入用户真实做过的事

【输入】用户原始项目条目（JSON）。
【输出】改写后的项目条目（JSON），保持字段结构。
保持 achievements 是 list[str]，tech_stack 是 list[str]，description 是 str，role 是 str。

只返回 JSON，不要其他文字。"""


SECTIONS: List[Dict[str, Any]] = [
    {
        "key": "header",
        "name": "个人信息",
        "skippable": False,
        "derived": False,
        "max_rounds": 3,
        "task": "采集姓名、手机、邮箱、微信（可选）、LinkedIn（可选）。1-2 轮问完。",
        "must_have": "姓名（必填）；手机/邮箱至少一项；微信/LinkedIn 可选",
        "schema": '{"name": "", "contact": {"phone": "", "email": "", "wechat": "", "linkedin": ""}}',
    },
    {
        "key": "education",
        "name": "教育经历",
        "skippable": False,
        "derived": False,
        "max_rounds": 4,
        "task": "先问'你有几段教育经历？'得到 N，再逐个问学校/专业/学历/起止年份。",
        "must_have": "至少 1 段教育经历，包含学校 + 专业 + 学历",
        "schema": '[{"school": "", "degree": "", "major": "", "start_year": "", "end_year": ""}]',
    },
    {
        "key": "experience",
        "name": "工作经历",
        "skippable": True,
        "derived": False,
        "max_rounds": 8,
        "task": (
            "先问'你有几段相关工作/实习经历想写进简历？'得到 N。"
            "再按顺序逐个深挖：公司、职位、起止、STAR 量化成果。"
            "**每段经历至少问 1 轮**，不能挖完第 1 段就跳过其他。"
            "用户答'应届无经验/没有'回复一句确认后输出 [SECTION_DONE,SKIP]。"
        ),
        "must_have": "每段经历：公司 + 职位 + 起止 + 至少 1 个量化成果",
        "schema": '[{"title": "", "company": "", "duration": "", "achievements": [""]}]',
    },
    {
        "key": "projects",
        "name": "项目经历",
        "skippable": True,
        "derived": False,
        "max_rounds": 8,
        "task": (
            "先问'你有几个想重点突出的项目？'得到 N。"
            "再按顺序逐个问：项目名、角色、技术栈、做了什么、量化成果。"
            "**每个项目至少问 1 轮**。N=0 / 用户说没有 → [SECTION_DONE,SKIP]。"
        ),
        "must_have": "每个项目：项目名 + 你的角色 + 技术栈 + 主要成果",
        "schema": '[{"name": "", "role": "", "description": "", "tech_stack": [""], "achievements": [""]}]',
    },
    {
        "key": "skills",
        "name": "技能",
        "skippable": False,
        "derived": False,
        "max_rounds": 2,
        "task": "采集技术栈（编程语言、框架、工具）+ 关键软技能。1 轮问完。",
        "must_have": "至少 3-5 项技能",
        "schema": '{"skills": [""]}',
    },
    {
        "key": "languages",
        "name": "语言能力",
        "skippable": True,
        "derived": False,
        "max_rounds": 2,
        "task": "采集语言能力。例：中文（母语）、英语（CET-6 / IELTS 7.0 / 流利）。1 轮问完，没有就 SKIP。",
        "must_have": "无（可整段跳过）",
        "schema": '{"languages": [{"name": "", "level": ""}]}',
    },
    {
        "key": "summary",
        "name": "个人总结",
        "skippable": False,
        "derived": True,
        "max_rounds": 0,
        "task": None,
        "must_have": None,
        "schema": None,
    },
    {
        "key": "core_competencies",
        "name": "核心能力",
        "skippable": False,
        "derived": True,
        "max_rounds": 0,
        "task": None,
        "must_have": None,
        "schema": None,
    },
]


def _get_section(key: str) -> Optional[Dict[str, Any]]:
    for s in SECTIONS:
        if s["key"] == key:
            return s
    return None


class ResumeFlowA:
    """0→1 对话式简历生成"""

    def __init__(self, llm_client, db: Any = None):
        self.llm_client = llm_client
        self.generator = ResumeGenerator()
        self.db = db

    # ----------------------------------------------------------------
    # Step 1: section 状态机对话与提取
    # ----------------------------------------------------------------

    def _build_chat_messages(
        self,
        section_key: str,
        messages: List[Dict[str, str]],
        collected_so_far: Dict[str, Any],
        industry: str,
        position: str,
    ) -> tuple[List[LLMMessage], bool, int]:
        """构建 chat section 的 LLM messages + force_close flag + rounds_used。"""
        section = _get_section(section_key)
        if not section:
            raise ValueError(f"Unknown section_key: {section_key}")
        if section.get("derived"):
            raise ValueError(f"Section {section_key} is derived, not chat-collectable")

        rounds_used = sum(1 for m in messages if m["role"] == "assistant")
        max_rounds = section["max_rounds"]
        force_close = rounds_used >= max_rounds

        collected_summary_lines = []
        for k, v in (collected_so_far or {}).items():
            if v and k != section_key:
                if k == "projects" and isinstance(v, list):
                    roles = []
                    for p in v:
                        r = p.get("role") if isinstance(p, dict) else None
                        if r:
                            roles.append(r)
                    if roles:
                        collected_summary_lines.append(f"- projects: 已采集 {len(v)} 个项目，角色：{', '.join(roles)}（如果后续项目角色相同，不要重复确认）")
                        continue
                preview = json.dumps(v, ensure_ascii=False)[:400]
                collected_summary_lines.append(f"- {k}: {preview}")
        collected_summary = "\n".join(collected_summary_lines) if collected_summary_lines else "（暂无）"

        system_text = _SECTION_CHAT_SYSTEM.format(
            section_name=section["name"],
            section_task=section["task"],
            section_must_have=section["must_have"],
            max_rounds=max_rounds,
            collected_summary=collected_summary,
            industry=industry,
            position=position,
        )
        if force_close:
            system_text += "\n\n【强制收尾】已达本段轮次上限，直接输出 [SECTION_DONE]。"

        llm_messages = [LLMMessage(role="system", content=system_text)]
        for m in messages:
            llm_messages.append(LLMMessage(role=m["role"], content=m["content"]))
        return llm_messages, force_close, rounds_used

    @staticmethod
    def _parse_chat_reply(content: str, force_close: bool, rounds_used: int) -> Dict[str, Any]:
        """把 LLM 完整回复解析成 reply dict。"""
        content = content.strip()
        if "[SECTION_DONE,SKIP]" in content or "[SECTION_DONE, SKIP]" in content:
            return {
                "type": "section_skipped",
                "message": content.replace("[SECTION_DONE,SKIP]", "").replace("[SECTION_DONE, SKIP]", "").strip(),
                "rounds_used": rounds_used,
            }
        if "[SECTION_DONE]" in content or force_close:
            return {
                "type": "section_done",
                "message": content.replace("[SECTION_DONE]", "").strip(),
                "rounds_used": rounds_used,
            }
        return {"type": "question", "message": content, "rounds_used": rounds_used}

    async def chat_section(
        self,
        section_key: str,
        messages: List[Dict[str, str]],
        collected_so_far: Dict[str, Any],
        industry: str,
        position: str,
    ) -> Dict[str, Any]:
        """在单个 section 内多轮对话。LLM 判断段是否问完。

        Returns:
            {"type": "question"|"section_done"|"section_skipped",
             "message": str, "rounds_used": int}
        """
        llm_messages, force_close, rounds_used = self._build_chat_messages(
            section_key, messages, collected_so_far, industry, position,
        )
        response: LLMResponse = await self.llm_client.analyze(
            messages=llm_messages, max_tokens=600, temperature=0.6,
        )
        return self._parse_chat_reply(response.content, force_close, rounds_used)

    async def extract_section(
        self,
        section_key: str,
        messages: List[Dict[str, str]],
    ) -> Any:
        """只提取当前 section 的结构化数据。"""
        section = _get_section(section_key)
        if not section or section.get("derived"):
            raise ValueError(f"Cannot extract section {section_key}")

        convo_text = "\n".join(
            f"{'👤' if m['role'] == 'user' else '🤖'}: {m['content']}"
            for m in messages
        )
        system_text = _SECTION_EXTRACT_SYSTEM.format(
            section_name=section["name"],
            section_schema=section["schema"],
        )
        llm_messages = [
            LLMMessage(role="system", content=system_text),
            LLMMessage(
                role="user",
                content=f"从以下对话中提取 {section['name']} 数据：\n\n{convo_text}",
            ),
        ]

        try:
            response: LLMResponse = await self.llm_client.analyze(
                messages=llm_messages, max_tokens=1000, temperature=0.2,
            )
            parsed = self._parse_json_loose(response.content)
        except Exception as exc:
            logger.warning(f"Flow A extract_section({section_key}) failed: {exc}")
            parsed = None

        if parsed is None:
            # 兜底：返回空结构
            return self._empty_section_value(section_key)
        return self._strip_placeholders(parsed)

    async def derive_summary_and_competencies(
        self,
        collected: Dict[str, Any],
        industry: str,
        position: str,
        skeleton_text: str = "",
    ) -> Dict[str, Any]:
        """采集完所有 section 后，LLM 派生 summary 和 core_competencies。

        skeleton_text: 由 build_skeleton 蒸馏出的岗位核心要求文本。传了就让 LLM
        派生 summary / 核心能力时朝岗位要求靠拢；空字符串则降级为纯用户数据派生。
        """
        skeleton_block = skeleton_text.strip() if skeleton_text else "（无可用岗位要求参考，请基于用户数据派生通用性更强的核心能力）"
        prompt = (
            f"已采集的简历数据：\n{json.dumps(collected, ensure_ascii=False, indent=2)}\n\n"
            f"请基于以上数据派生 summary（1-2 句）和 core_competencies（3-5 条）。"
        )
        llm_messages = [
            LLMMessage(
                role="system",
                content=_DERIVE_SYSTEM.format(
                    industry=industry, position=position, skeleton_block=skeleton_block,
                ),
            ),
            LLMMessage(role="user", content=prompt),
        ]
        try:
            response: LLMResponse = await self.llm_client.analyze(
                messages=llm_messages, max_tokens=600, temperature=0.4,
            )
            parsed = self._parse_json(response.content)
        except Exception as exc:
            logger.warning(f"Flow A derive_summary failed: {exc}")
            parsed = None

        parsed = parsed or {}
        return {
            "summary": self._strip_placeholders(parsed.get("summary", "") or ""),
            "core_competencies": self._strip_placeholders(parsed.get("core_competencies", []) or []),
        }

    async def rewrite_experience(
        self,
        collected: Dict[str, Any],
        industry: str,
        position: str,
        skeleton_text: str = "",
    ) -> List[Dict[str, Any]]:
        """对每段工作经历用 LLM + RAG skeleton 做岗位化改写。

        把不相关经历往目标岗位上靠，保留事实不编造，只改 description 和 achievements。
        返回改写后的 experience list（原样字段结构）。失败时返回原 list 不阻断流程。
        """
        original = collected.get("experience") or []
        if not original:
            return []

        skeleton_block = skeleton_text.strip() if skeleton_text else "（无可用岗位要求参考，做通用润色）"
        rewritten: List[Dict[str, Any]] = []
        for idx, exp in enumerate(original):
            try:
                prompt = f"原始经历条目 #{idx + 1}：\n{json.dumps(exp, ensure_ascii=False, indent=2)}"
                llm_messages = [
                    LLMMessage(
                        role="system",
                        content=_REWRITE_EXPERIENCE_SYSTEM.format(
                            industry=industry, position=position, skeleton_block=skeleton_block,
                        ),
                    ),
                    LLMMessage(role="user", content=prompt),
                ]
                response: LLMResponse = await self.llm_client.analyze(
                    messages=llm_messages, max_tokens=800, temperature=0.5,
                )
                parsed = self._parse_json_loose(response.content)
                if isinstance(parsed, dict):
                    for k in ("title", "company", "duration"):
                        if k in exp and k not in parsed:
                            parsed[k] = exp[k]
                    if "achievements" not in parsed:
                        parsed["achievements"] = exp.get("achievements", [])
                    if "description" not in parsed:
                        parsed["description"] = exp.get("description", "")
                    rewritten.append(parsed)
                else:
                    rewritten.append(exp)
            except Exception as exc:
                logger.warning(f"Flow A rewrite_experience[{idx}] failed: {exc}")
                rewritten.append(exp)
        return rewritten

    async def rewrite_projects(
        self,
        collected: Dict[str, Any],
        industry: str,
        position: str,
        skeleton_text: str = "",
    ) -> List[Dict[str, Any]]:
        """对每个项目经历做岗位化改写，保留 tech_stack 和 role，只改 description 和 achievements。"""
        original = collected.get("projects") or []
        if not original:
            return []

        skeleton_block = skeleton_text.strip() if skeleton_text else "（无可用岗位要求参考，做通用润色）"
        rewritten: List[Dict[str, Any]] = []
        for idx, proj in enumerate(original):
            try:
                prompt = f"原始项目条目 #{idx + 1}：\n{json.dumps(proj, ensure_ascii=False, indent=2)}"
                llm_messages = [
                    LLMMessage(
                        role="system",
                        content=_REWRITE_PROJECTS_SYSTEM.format(
                            industry=industry, position=position, skeleton_block=skeleton_block,
                        ),
                    ),
                    LLMMessage(role="user", content=prompt),
                ]
                response: LLMResponse = await self.llm_client.analyze(
                    messages=llm_messages, max_tokens=800, temperature=0.5,
                )
                parsed = self._parse_json_loose(response.content)
                if isinstance(parsed, dict):
                    for k in ("name", "role", "tech_stack"):
                        if k in proj and k not in parsed:
                            parsed[k] = proj[k]
                    if "achievements" not in parsed:
                        parsed["achievements"] = proj.get("achievements", [])
                    if "description" not in parsed:
                        parsed["description"] = proj.get("description", "")
                    rewritten.append(parsed)
                else:
                    rewritten.append(proj)
            except Exception as exc:
                logger.warning(f"Flow A rewrite_projects[{idx}] failed: {exc}")
                rewritten.append(proj)
        return rewritten

    @staticmethod
    def _empty_section_value(section_key: str) -> Any:
        """每个 section 提取失败时的兜底空值结构。"""
        if section_key == "header":
            return {"name": "", "contact": {"phone": "", "email": "", "wechat": "", "linkedin": ""}}
        if section_key in ("experience", "projects", "education"):
            return []
        if section_key == "skills":
            return {"skills": []}
        if section_key == "languages":
            return {"languages": []}
        return {}

    def _parse_json_loose(self, text: str) -> Any:
        """提取 JSON。section 提取的输出可能是 list 也可能是 dict，要兼容。"""
        # 先试 dict
        s_obj = text.find("{")
        s_arr = text.find("[")
        if s_obj < 0 and s_arr < 0:
            return None
        if s_arr >= 0 and (s_obj < 0 or s_arr < s_obj):
            e_arr = text.rfind("]") + 1
            try:
                return json.loads(text[s_arr:e_arr])
            except json.JSONDecodeError:
                pass
        e_obj = text.rfind("}") + 1
        if s_obj >= 0 and e_obj > s_obj:
            try:
                return json.loads(text[s_obj:e_obj])
            except json.JSONDecodeError:
                pass
        return None

    # ----------------------------------------------------------------
    # Step 2: RAG 骨架 — 从存量 JD 中提取该岗位的高频要求
    # ----------------------------------------------------------------

    async def build_skeleton(self, position: str, industry: str) -> Dict[str, Any]:
        """RAG 检索该岗位的存量 JD，提取高频要求作为简历骨架。

        Returns:
            {"text": str, "source": "rag"|"fallback", "n_chunks": int,
             "industries_covered": List[str]}
            空召回时 source="fallback"，下游 UI 可提示用户该岗位 JD 较少。
        """
        chunks = self._retrieve_rag_chunks(position, industry, top_k=15)
        if not chunks:
            logger.info(f"Flow A: no RAG chunks for {position}; using fallback skeleton")
            return {
                "text": self._fallback_skeleton(position),
                "source": "fallback",
                "n_chunks": 0,
                "industries_covered": [],
            }

        # 只保留 requirement / responsibility 类，过滤其他噪声
        useful = [c for c in chunks if c.get("chunk_type") in ("requirement", "responsibility")]
        if not useful:
            useful = chunks  # 兜底：拿到啥用啥

        industries = sorted({
            (c.get("metadata", {}) or {}).get("jd_industry_tag")
            for c in useful
            if (c.get("metadata", {}) or {}).get("jd_industry_tag")
        })

        combined = "\n---\n".join((c.get("chunk_text") or "")[:300] for c in useful[:10])
        prompt = (
            f"从以下 {len(useful)} 条 {position} 岗位的 JD 要求片段中（覆盖"
            f"{('、'.join(industries) + '等' + str(len(industries)) + ' 个') if industries else '多个'}行业），"
            f"提炼出 5-8 条最核心、最通用的能力要求（每条 10-20 字）。\n\n"
            f"{combined}\n\n请用列表格式返回，每行一条要求。"
        )
        try:
            response: LLMResponse = await self.llm_client.analyze(
                messages=[
                    LLMMessage(role="system", content="你是招聘需求分析专家。"),
                    LLMMessage(role="user", content=prompt),
                ],
                max_tokens=300,
                temperature=0.3,
            )
            return {
                "text": response.content.strip(),
                "source": "rag",
                "n_chunks": len(useful),
                "industries_covered": industries,
            }
        except Exception as exc:
            logger.warning(f"Flow A skeleton extraction failed: {exc}")
            return {
                "text": self._fallback_skeleton(position),
                "source": "fallback",
                "n_chunks": len(useful),
                "industries_covered": industries,
            }

    @staticmethod
    def _fallback_skeleton(position: str) -> str:
        """空召回兜底：给一份通用、稳健的能力清单，避免下游 prompt 缺骨架。"""
        return (
            f"【{position} 通用能力骨架（JD 库样本较少，使用通用模板）】\n"
            f"- 良好的沟通与跨部门协同能力\n"
            f"- 数据驱动的问题分析与决策能力\n"
            f"- 业务理解力，能将业务需求转化为可执行方案\n"
            f"- 项目推进与目标达成能力\n"
            f"- 学习能力强，能快速适应新业务/新工具\n"
            f"- 良好的逻辑表达与文档撰写能力"
        )

    def _retrieve_rag_chunks(
        self, position: str, industry: str, top_k: int
    ) -> List[Dict[str, Any]]:
        """检索与目标岗位相关的存量 JD chunks。

        策略：纯语义召回 + chunk_type=requirement 优先 + industry 软加权。
        不做 position 硬 JOIN —— 现实里 JD 库的 position_tag 覆盖率极低
        （多数 JD 是采集进来未跑 classifier 的），硬 JOIN 等于把召回打死。
        召回 query 同时拼 industry，让向量相似度自然承担 position+industry 加权。
        requirement 类不够时回退到不限 chunk_type 再试一次。
        """
        try:
            from tools.retriever import Retriever
            retriever = Retriever(db=self.db)
            query = f"{position} {industry}".strip()
            # 优先 requirement 类，相似度阈值放低（0.3）让语义空间自己排序
            results = retriever.retrieve(
                query,
                top_k=top_k,
                filter_chunk_type="requirement",
                boost_industry=industry,
                min_similarity=0.3,
            )
            if results:
                return results
            # requirement 类太少时不限 chunk_type
            return retriever.retrieve(
                query, top_k=top_k, boost_industry=industry, min_similarity=0.3,
            )
        except Exception as exc:
            logger.warning(f"Flow A RAG retrieval failed: {exc}")
            return []

    # ----------------------------------------------------------------
    # 工具方法
    # ----------------------------------------------------------------

    def _parse_json(self, text: str) -> Optional[Dict[str, Any]]:
        """从 LLM 返回文本中提取 JSON"""
        json_start = text.find("{")
        json_end = text.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            try:
                return json.loads(text[json_start:json_end])
            except json.JSONDecodeError as exc:
                logger.warning(f"Flow A JSON parse failed: {exc}")
        return None

    @staticmethod
    def _strip_placeholders(value: Any) -> Any:
        """递归剥除 LLM 偷塞的占位符（[您的姓名]、[X]年、202X.XX、xxx、待补充 等）。

        把它们替换成空字符串/空列表，让前端渲染出"该字段空缺"而不是"看起来像模板"。
        """
        import re
        # 命中模式：方括号包裹、202X 这种带 X 的年份、纯 xxx/XXX、明文"待补充/待填写/占位"
        _PLACEHOLDER_RE = re.compile(
            r"\[[^\]]*\]"          # [您的姓名] [X]年 [前一家公司]
            r"|20\d{0,2}[xX]+\S*"  # 202X.XX 20XX
            r"|(?<![A-Za-z])[xX]{3,}(?![A-Za-z])"  # 单独的 xxx XXX
            r"|待补充|待填写|占位符?|TBD|tbd",
        )

        if isinstance(value, str):
            cleaned = _PLACEHOLDER_RE.sub("", value).strip(" ，、,;；|｜·-—")
            # 剥完只剩标点/空白 → 视为空
            return "" if not cleaned or cleaned in {"，", "。", "/"} else cleaned
        if isinstance(value, list):
            cleaned_list = [ResumeFlowA._strip_placeholders(v) for v in value]
            # 元素剥完是空 dict / 空 str 的过滤掉
            return [v for v in cleaned_list if v not in ("", None, {}, [])]
        if isinstance(value, dict):
            return {k: ResumeFlowA._strip_placeholders(v) for k, v in value.items()}
        return value

    @staticmethod
    def _normalize_resume_shape(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """保证 to_markdown / 入库代码看到的字段都齐全，不会因为 LLM 缺字段炸掉。

        同时剥掉 LLM 偷塞的占位符，避免简历看着像 ChatGPT 模板。
        """
        d = ResumeFlowA._strip_placeholders(data or {})
        if not isinstance(d, dict):
            d = {}
        header = d.get("header") or {}
        if not isinstance(header, dict):
            header = {}
        contact = header.get("contact") or {}
        if not isinstance(contact, dict):
            contact = {}
        # 新派生字段：summary 顶层；header.summary 仍兼容
        top_summary = d.get("summary", "")
        if not top_summary:
            top_summary = header.get("summary", "") or ""
        return {
            "header": {
                "name": header.get("name", "") or "",
                "contact": {
                    "phone": contact.get("phone", "") or "",
                    "email": contact.get("email", "") or "",
                    "wechat": contact.get("wechat", "") or "",
                    "linkedin": contact.get("linkedin", "") or "",
                },
                "summary": top_summary,
            },
            "summary": top_summary,
            "core_competencies": d.get("core_competencies") or [],
            "experience": d.get("experience") or [],
            "skills": d.get("skills") or [],
            "education": d.get("education") or [],
            "projects": d.get("projects") or [],
            "languages": d.get("languages") or [],
        }

    def to_markdown(self, resume_data: Dict[str, Any]) -> str:
        return self.generator.to_markdown(resume_data)

    def to_html(self, resume_data: Dict[str, Any]) -> str:
        return self.generator.to_html(resume_data)