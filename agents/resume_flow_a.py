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

对话原则：
1. 每轮只问 1-2 个问题，不要一次性列出所有问题
2. 根据用户的回答自然追问，挖掘具体数据、成果和量化指标
3. 用户回答模糊时追一句具体细节（如"这个项目你具体负责什么？"）
4. 当你认为信息足够完整时，在回复末尾加上 [DONE]

你需要收集的信息（逐步覆盖，不要跳步）：
- 基本信息：姓名、目标岗位、联系方式
- 工作经历：公司名、职位、起止时间、职责、量化成果
- 技能：技术技能、工具、软技能
- 教育背景：学校、学历、专业、毕业年份
- 项目经验：项目名称、你的角色、技术栈、成果

当信息足够完整时，回复格式：
好的，我已经了解了你的背景，现在为你生成简历。

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

    def __init__(self, llm_client):
        self.llm_client = llm_client
        self.generator = ResumeGenerator()

    # ----------------------------------------------------------------
    # Step 1: 对话
    # ----------------------------------------------------------------

    async def chat(
        self,
        messages: List[Dict[str, str]],
        industry: str,
        position: str,
    ) -> Dict[str, Any]:
        """
        发送对话消息，返回 LLM 的回复。

        Returns:
            {"type": "question", "message": "..."}  — 继续对话
            {"type": "done", "message": "..."}       — 信息收集完毕
        """
        llm_messages = [
            LLMMessage(
                role="system",
                content=f"{_CONVERSATION_SYSTEM}\n\n用户目标行业：{industry}\n用户目标岗位：{position}",
            )
        ]
        for m in messages:
            llm_messages.append(LLMMessage(role=m["role"], content=m["content"]))

        response: LLMResponse = await self.llm_client.analyze(
            messages=llm_messages, max_tokens=800, temperature=0.7,
        )
        content = response.content.strip()

        if "[DONE]" in content:
            return {"type": "done", "message": content.replace("[DONE]", "").strip()}
        return {"type": "question", "message": content}

    # ----------------------------------------------------------------
    # Step 2: 从对话中提取结构化简历
    # ----------------------------------------------------------------

    async def extract_resume(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """从完整对话历史中提取结构化简历数据"""
        convo_text = "\n".join(
            f"{'👤' if m['role'] == 'user' else '🤖'}: {m['content']}" for m in messages
        )
        llm_messages = [
            LLMMessage(role="system", content=_EXTRACT_SYSTEM),
            LLMMessage(role="user", content=f"从以下对话中提取简历数据：\n\n{convo_text}"),
        ]

        response: LLMResponse = await self.llm_client.analyze(
            messages=llm_messages, max_tokens=2000, temperature=0.2,
        )
        return self._parse_json(response.content)

    # ----------------------------------------------------------------
    # Step 3: RAG 骨架 — 从存量 JD 中提取该岗位的高频要求
    # ----------------------------------------------------------------

    async def build_skeleton(self, position: str, industry: str) -> str:
        """RAG 检索该岗位的存量 JD，提取高频要求作为简历骨架"""
        chunks = self._retrieve_rag_chunks(position, industry, top_k=15)
        if not chunks:
            logger.info(f"Flow A: no RAG chunks found for {position} in {industry}")
            return ""

        # 聚合 requirement 类 chunk 的文本
        requirement_texts = []
        for c in chunks:
            if c.get("chunk_type") in ("requirement", "responsibility"):
                requirement_texts.append(c.get("chunk_text", ""))

        if not requirement_texts:
            return ""

        # 用 LLM 提炼高频要求关键词
        combined = "\n---\n".join(t[:300] for t in requirement_texts[:10])
        prompt = f"""从以下 {len(requirement_texts)} 条 {position} 岗位的 JD 要求片段中，提炼出 5-8 条最核心、最通用的要求（每条 10-20 字）。

{combined}

请用列表格式返回，每行一条要求。"""
        try:
            response: LLMResponse = await self.llm_client.analyze(
                messages=[
                    LLMMessage(role="system", content="你是招聘需求分析专家。"),
                    LLMMessage(role="user", content=prompt),
                ],
                max_tokens=300,
                temperature=0.3,
            )
            return response.content.strip()
        except Exception as exc:
            logger.warning(f"Flow A skeleton extraction failed: {exc}")
            return ""

    def _retrieve_rag_chunks(
        self, position: str, industry: str, top_k: int
    ) -> List[Dict[str, Any]]:
        """检索与目标岗位相关的存量 JD chunks"""
        try:
            from tools.retriever import Retriever
            retriever = Retriever()
            # 先用 position 作为查询词搜索
            results = retriever.retrieve(
                position, top_k=top_k, filter_chunk_type="requirement", min_similarity=0.4,
            )
            if not results:
                # 降级：不按 chunk_type 过滤
                results = retriever.retrieve(position, top_k=top_k, min_similarity=0.3)
            return results
        except Exception as exc:
            logger.warning(f"Flow A RAG retrieval failed: {exc}")
            return []

    # ----------------------------------------------------------------
    # Step 4: 生成最终简历
    # ----------------------------------------------------------------

    async def generate_final(
        self,
        extracted: Dict[str, Any],
        skeleton: str,
        position: str,
    ) -> Dict[str, Any]:
        """结合用户数据 + RAG 骨架，生成最终简历"""
        skeleton_block = (
            f"\n\n【目标岗位核心要求（来自行业 JD 分析）】\n{skeleton}"
            if skeleton
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

        response: LLMResponse = await self.llm_client.analyze(
            messages=llm_messages, max_tokens=3000, temperature=0.4,
        )
        return self._parse_json(response.content) or extracted

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

    def to_markdown(self, resume_data: Dict[str, Any]) -> str:
        return self.generator.to_markdown(resume_data)

    def to_html(self, resume_data: Dict[str, Any]) -> str:
        return self.generator.to_html(resume_data)