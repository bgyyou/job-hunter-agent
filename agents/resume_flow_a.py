# -*- coding: utf-8 -*-
"""
Flow A: 0→1 对话式简历生成 Agent

流程：
  行业选择 → 岗位选择 → LLM 多轮对话 → 结构化提取 → RAG 骨架 → 生成简历

与 BaseAgent 框架无关，是一个独立的状态机 + LLM 对话循环。
因为 Flow A 的"规划"由 LLM 自主完成（对话节奏），不需要代码层的 plan/recover/reflect。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from tools.generator.resume_generator import ResumeGenerator
from tools.llm import LLMMessage, LLMResponse


_CONVERSATION_SYSTEM = """你是专业的简历助手。你的任务是通过对话了解用户的职业背景，最终生成一份完整、专业的简历。

【硬性约束】
1. 每轮只问 1-2 个问题，绝不一次性列出所有问题
2. 你最多可以问 {max_rounds} 轮问题；接近上限时果断收尾，不要纠结细枝末节
3. 当信息足够完整、或已达到轮次上限时，在回复末尾加上 [DONE]

【分层深挖策略 — 按这个顺序，逐层推进】
L1（必问，约 1 轮）：姓名、目标岗位的相关年限、最近一段工作经历的公司/职位/时间
L2（深挖最近一段经历，约 2-3 轮）：用 STAR 法则拆解
   - Situation：业务背景、团队规模、当时的难题
   - Task：你被分派的具体目标/KPI
   - Action：你具体做了什么（动词+对象）
   - Result：量化结果（用户数/收入/效率提升/上线时间）—— 没数字就追问"大概是多少"
L3（深挖第二段经历，约 2-3 轮）：同 STAR，可适当压缩
L4（兜底补齐，约 1-2 轮）：技能栈、教育背景、关键项目（如果前面没覆盖）

【追问原则】
- 用户回答模糊（如"做过几个项目"）→ 追"哪几个？最有代表性的是哪个？"
- 用户给笼统形容词（如"提升了很多"）→ 追"具体数字呢？比如 30% 还是 3 倍？"
- 用户跳过某个层 → 把它拉回来，但不要重复问已答内容

【完成标志】
当 L1-L4 至少各覆盖 1 次、或达到 {max_rounds} 轮时：
好的，信息够了，我来生成简历。

[DONE]"""

_EXTRACT_SYSTEM = """你是简历数据提取专家。从对话历史中提取用户的职业信息，输出 JSON。

要求：
1. 只提取用户明确提到的信息，不要编造
2. 缺失的字段留空或默认值，不要猜测
3. 工作经历、项目经验中的描述要保留用户原始措辞，仅做轻微润色

输出 JSON 结构：
{
    "header": {
        "name": "姓名",
        "contact": {"phone": "手机", "email": "邮箱"},
        "summary": "一句话个人陈述（从经历中提炼）"
    },
    "experience": [
        {"title": "职位", "company": "公司", "duration": "2020-2023", "achievements": ["成果1", "成果2"]}
    ],
    "skills": ["技能1", "技能2"],
    "education": [{"school": "学校", "degree": "学历", "major": "专业", "start_year": "入学年份", "end_year": "毕业年份"}],
    "projects": [{"name": "项目名", "role": "角色", "description": "描述", "tech_stack": ["技术"]}]
}

只返回 JSON，不要其他文字。"""

_GENERATE_SYSTEM = """你是资深简历优化专家。根据用户的职业背景和目标岗位的行业要求，生成一份专业的、针对目标岗位优化的简历。

原则：
1. **真实性**：不编造经历，只调整表达方式让简历更专业
2. **针对性**：对照行业要求，强化相关技能和经验的描述
3. **量化**：保留用户提供的具体数据，用 STAR 法则组织经历描述
4. **格式**：返回完整的简历 JSON，保持标准结构

返回 JSON 结构：
{
    "header": {
        "name": "...",
        "contact": {"phone": "...", "email": "..."},
        "summary": "针对目标岗位的一句话总结"
    },
    "experience": [{"title": "...", "company": "...", "duration": "...", "achievements": ["..."]}],
    "skills": ["..."],
    "education": [{"school": "...", "degree": "...", "major": "...", "start_year": "", "end_year": ""}],
    "projects": [{"name": "...", "role": "...", "description": "...", "tech_stack": ["..."]}]
}

只返回 JSON，不要其他文字。"""


class ResumeFlowA:
    """0→1 对话式简历生成"""

    def __init__(self, llm_client, db: Any = None):
        self.llm_client = llm_client
        self.generator = ResumeGenerator()
        self.db = db

    # ----------------------------------------------------------------
    # Step 1: 对话
    # ----------------------------------------------------------------

    async def chat(
        self,
        messages: List[Dict[str, str]],
        industry: str,
        position: str,
        max_rounds: int = 8,
    ) -> Dict[str, Any]:
        """
        发送对话消息，返回 LLM 的回复。

        Args:
            messages: [{"role": "user|assistant", "content": "..."}, ...]
            industry / position: 三级下拉选出的目标
            max_rounds: AI 最多问几轮（N=8 深度模式，N=4 商业速度模式）。
                超过此轮次时强制注入收尾指令，确保 LLM 输出 [DONE]。

        Returns:
            {"type": "question", "message": "..."}  — 继续对话
            {"type": "done", "message": "..."}      — 信息收集完毕
        """
        rounds_used = sum(1 for m in messages if m["role"] == "assistant")
        force_close = rounds_used >= max_rounds

        system_text = _CONVERSATION_SYSTEM.format(max_rounds=max_rounds)
        system_text += f"\n\n用户目标行业：{industry}\n用户目标岗位：{position}"
        system_text += f"\n当前进度：你已问过 {rounds_used}/{max_rounds} 轮。"
        if force_close:
            system_text += (
                "\n\n【强制收尾】已达到轮次上限。本轮不要再问新问题，"
                "直接用 1-2 句话感谢用户，并以 [DONE] 结束。"
            )
        elif rounds_used >= max_rounds - 1:
            system_text += (
                "\n\n【提示】只剩最后 1 轮预算。如果还有关键空白（如缺联系方式、"
                "缺最近一段经历的量化结果），优先问；否则直接收尾输出 [DONE]。"
            )

        llm_messages = [LLMMessage(role="system", content=system_text)]
        for m in messages:
            llm_messages.append(LLMMessage(role=m["role"], content=m["content"]))

        response: LLMResponse = await self.llm_client.analyze(
            messages=llm_messages, max_tokens=800, temperature=0.7,
        )
        content = response.content.strip()

        if "[DONE]" in content or force_close:
            return {
                "type": "done",
                "message": content.replace("[DONE]", "").strip(),
                "rounds_used": rounds_used,
            }
        return {"type": "question", "message": content, "rounds_used": rounds_used}

    # ----------------------------------------------------------------
    # Step 2: 从对话中提取结构化简历
    # ----------------------------------------------------------------

    async def extract_resume(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """从完整对话历史中提取结构化简历数据。

        LLM 解析失败时返回一份"骨架可见"的兜底字典：用户至少能看到自己说过的内容，
        而不是空白页。下游 ``generate_final`` 会拿这份骨架再走一次润色 LLM。
        """
        convo_text = "\n".join(
            f"{'👤' if m['role'] == 'user' else '🤖'}: {m['content']}" for m in messages
        )
        llm_messages = [
            LLMMessage(role="system", content=_EXTRACT_SYSTEM),
            LLMMessage(role="user", content=f"从以下对话中提取简历数据：\n\n{convo_text}"),
        ]

        try:
            response: LLMResponse = await self.llm_client.analyze(
                messages=llm_messages, max_tokens=2000, temperature=0.2,
            )
            parsed = self._parse_json(response.content)
        except Exception as exc:
            logger.warning(f"Flow A extract_resume LLM call failed: {exc}")
            parsed = None

        if parsed:
            return self._normalize_resume_shape(parsed)

        # 兜底：把用户的回答原文塞进 summary，让生成阶段有素材可用
        user_raw = "\n".join(
            m["content"] for m in messages if m.get("role") == "user"
        )[:1500]
        logger.warning("Flow A extract_resume parse failed — using raw user text fallback")
        return {
            "header": {"name": "", "contact": {"phone": "", "email": ""}, "summary": user_raw},
            "experience": [],
            "skills": [],
            "education": [],
            "projects": [],
        }

    # ----------------------------------------------------------------
    # Step 3: RAG 骨架 — 从存量 JD 中提取该岗位的高频要求
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
    # Step 4: 生成最终简历
    # ----------------------------------------------------------------

    async def generate_final(
        self,
        extracted: Dict[str, Any],
        skeleton: Dict[str, Any],
        position: str,
    ) -> Dict[str, Any]:
        """结合用户数据 + RAG 骨架，生成最终简历。skeleton 由 build_skeleton 返回。"""
        skeleton_text = (skeleton or {}).get("text", "")
        skeleton_block = (
            f"\n\n【目标岗位核心要求（来自行业 JD 分析）】\n{skeleton_text}"
            if skeleton_text
            else ""
        )

        prompt = (
            f"目标岗位：{position}{skeleton_block}\n\n"
            f"用户职业背景：\n{json.dumps(extracted, ensure_ascii=False, indent=2)}\n\n"
            f"请生成一份针对 {position} 优化的简历 JSON。"
        )

        llm_messages = [
            LLMMessage(role="system", content=_GENERATE_SYSTEM),
            LLMMessage(role="user", content=prompt),
        ]

        try:
            response: LLMResponse = await self.llm_client.analyze(
                messages=llm_messages, max_tokens=3000, temperature=0.4,
            )
            parsed = self._parse_json(response.content)
        except Exception as exc:
            logger.warning(f"Flow A generate_final LLM call failed: {exc}")
            parsed = None

        return self._normalize_resume_shape(parsed or extracted)

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
    def _normalize_resume_shape(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """保证 to_markdown / 入库代码看到的字段都齐全，不会因为 LLM 缺字段炸掉。"""
        d = data or {}
        header = d.get("header") or {}
        if not isinstance(header, dict):
            header = {}
        contact = header.get("contact") or {}
        if not isinstance(contact, dict):
            contact = {}
        return {
            "header": {
                "name": header.get("name", "") or "",
                "contact": {
                    "phone": contact.get("phone", "") or "",
                    "email": contact.get("email", "") or "",
                },
                "summary": header.get("summary", "") or "",
            },
            "experience": d.get("experience") or [],
            "skills": d.get("skills") or [],
            "education": d.get("education") or [],
            "projects": d.get("projects") or [],
        }

    def to_markdown(self, resume_data: Dict[str, Any]) -> str:
        return self.generator.to_markdown(resume_data)

    def to_html(self, resume_data: Dict[str, Any]) -> str:
        return self.generator.to_html(resume_data)