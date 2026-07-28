"""Coordinator chat helpers.

对话入口（chat_assistant / chat）与子入口（_chat_parse_resume / _chat_analyze_jd /
_chat_run_workflow / _chat_check_state / _chat_response）。
原 coordinator.py 行 292-346 + 1001-1389。
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional

from loguru import logger

from tools.llm import LLMMessage


class CoordinatorChatMixin:
    """Chat-related helpers. Expects self.llm_client, self.state, self.execute, etc."""

    async def chat_assistant(
        self,
        user_message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """v2.1 M6.A.3: AI 浮窗后端（轻量对话，不做意图路由）。

        注入项目上下文（当前简历 / 最近 JD / 匹配分）让回答贴合用户实际进度，
        而不是通用闲聊。context 为空时退化为通用 LLM 问答。

        与 chat() 区别：chat() 做意图分类 + 工具路由（重，每次 1-2 次 LLM 调用），
        本方法只走一次 LLM 直接对话，适合浮窗高频问答。
        """
        ctx = context or {}
        system_parts = [
            "你是 JobHunter 的求职助手。用户在 Streamlit 内通过浮窗与你对话。",
            "回答简洁、聚焦求职决策；不要编造用户没提供的经历或公司。",
        ]

        resume = ctx.get("resume")
        if resume:
            name = (resume.get("header") or {}).get("name") or resume.get("name") or "候选人"
            skills = resume.get("skills") or {}
            tech = skills.get("technical") if isinstance(skills, dict) else skills
            system_parts.append(
                f"【当前简历】姓名：{name}；技能：{', '.join(tech[:15]) if tech else 'N/A'}；"
                f"经验年数：{resume.get('experience_years', 'N/A')}"
            )

        jd = ctx.get("jd")
        if jd:
            system_parts.append(
                f"【最近 JD】{jd.get('title', 'N/A')} @ {jd.get('company', 'N/A')}；"
                f"关键词：{', '.join((jd.get('keywords') or [])[:10])}"
            )

        score = ctx.get("match_score")
        if score is not None:
            system_parts.append(f"【最近匹配分】{score}")

        history = ctx.get("history") or []
        messages = [LLMMessage(role="system", content="\n".join(system_parts))]
        for h in history[-6:]:
            if isinstance(h, LLMMessage):
                messages.append(h)
            else:
                messages.append(LLMMessage(role=h.get("role", "user"),
                                           content=h.get("content", "")))
        messages.append(LLMMessage(role="user", content=user_message))

        try:
            response = await self.llm_client.analyze(
                messages=messages, max_tokens=800, temperature=0.5, use_cache=False,
            )
            return {"status": "success", "reply": response.content}
        except Exception as e:
            return {"status": "error", "reply": f"⚠️ LLM 调用失败：{e}"}

    async def chat(self, user_message: str) -> Dict[str, Any]:
        """
        自然语言对话 - 理解用户意图并执行相应操作

        Args:
            user_message: 用户的自然语言输入

        Returns:
            包含回复和执行结果的字典
        """
        # 先做简单的关键词匹配，更可靠！
        lower_msg = user_message.lower()

        # 检查是否要分析匹配度
        match_keywords = ["匹配", "匹配度", "match", "分析匹配", "看看匹配"]
        if any(k in lower_msg for k in match_keywords):
            has_resume = "resume_data" in self.state
            has_jd = "jd_result" in self.state

            if has_resume and has_jd:
                # 已经有数据了，只是要显示分析
                return await self._chat_check_state()
            elif has_resume and not has_jd:
                return {
                    "status": "success",
                    "type": "chat",
                    "reply": "请先提供职位描述 (JD)，让我分析匹配度！"
                }
            elif has_jd and not has_resume:
                return {
                    "status": "success",
                    "type": "chat",
                    "reply": "请先提供您的简历，让我分析匹配度！"
                }
            else:
                return {
                    "status": "success",
                    "type": "chat",
                    "reply": "请先提供简历和职位描述！"
                }

        # 检查是否要查看状态
        state_keywords = ["状态", "state", "当前状态", "当前"]
        if any(k in lower_msg for k in state_keywords):
            return await self._chat_check_state()

        # 检查是否要解析简历（有文件路径或关键词）
        if any(ext in lower_msg for ext in [".pdf", ".docx", ".md", ".txt"]):
            return await self._chat_parse_resume(user_message, {})
        if any(k in lower_msg for k in ["解析简历", "parse resume", "读简历"]):
            return await self._chat_parse_resume(user_message, {})

        # 检查是否要分析 JD（长文本或有明确关键词）
        if len(user_message) > 100 and any(k in lower_msg for k in ["职位", "jd", "job", "要求", "职责"]):
            return await self._chat_analyze_jd(user_message, {"jd_text": user_message})
        if any(k in lower_msg for k in ["分析jd", "分析职位", "analyze jd"]):
            return await self._chat_analyze_jd(user_message, {})

        # 检查是否要运行完整工作流
        workflow_keywords = ["完整工作流", "优化简历", "生成简历", "cover letter", "求职信", "完整流程", "帮我申请", "run workflow"]
        if any(k in lower_msg for k in workflow_keywords):
            return await self._chat_run_workflow({})

        # 否则，用 LLM 理解意图
        state_summary = self._get_state_summary()

        prompt = f"""你是 Job Hunter Agent，一个专业的求职助手。

当前状态:
{state_summary}

可用工具:
1. parse_resume - 解析简历文件，需要参数: resume_file (文件路径) 或 resume_text (文本)
2. analyze_jd - 分析职位描述，需要参数: jd_text (文本) 或 jd_url (URL)
3. analyze_match - 分析简历与职位的匹配度（需要已解析简历和JD）
4. generate_optimization - 生成优化建议（需要已解析简历和JD）
5. generate_resume - 生成优化后简历（需要已解析简历）
6. generate_cover_letter - 生成求职信（需要已解析简历和JD）
7. submit_application - 投递职位
8. 无工具 - 只是聊天或回答问题

用户输入: "{user_message}"

请分析用户意图，以 JSON 格式返回:
{{
    "intent": "用户意图的简短描述",
    "action": "要执行的动作: chat|parse_resume|analyze_jd|run_workflow|check_state|other",
    "params": {{
        "resume_file": "如果要解析简历，这里填文件路径",
        "jd_text": "如果要分析JD，这里填JD文本",
        "jd_url": "如果要分析JD，这里填URL",
        "company_name": "如果是求职，这里填公司名"
    }},
    "needs_confirmation": false,
    "confirmation_question": "如果需要用户确认，这里填确认问题"
}}

只返回 JSON，不要其他内容！！！
"""

        try:
            # 调用 LLM 理解意图
            messages = [LLMMessage(role="user", content=prompt)]
            response = await self.llm_client.analyze(messages, max_tokens=1000)

            # 解析 LLM 的响应
            text = response.content.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]

            parsed = json.loads(text.strip())
            action = parsed.get("action", "chat")
            params = parsed.get("params", {})
            intent = parsed.get("intent", "")

            # 根据意图执行相应动作
            if action == "parse_resume":
                return await self._chat_parse_resume(user_message, params)
            elif action == "analyze_jd":
                return await self._chat_analyze_jd(user_message, params)
            elif action == "run_workflow":
                return await self._chat_run_workflow(params)
            elif action == "check_state":
                return await self._chat_check_state()
            else:
                return await self._chat_response(user_message, intent)

        except Exception as e:
            self.logger.error(f"解析意图失败: {e}")
            # LLM 解析失败时，给一个友好的回复
            return {
                "status": "success",
                "type": "chat",
                "reply": "我理解您的意思了！您可以：\n- 说 '解析简历: /path/to/resume.pdf' 来解析简历\n- 直接粘贴职位描述给我分析\n- 或者说 '查看状态' 看看当前进度"
            }

    async def _chat_parse_resume(self, user_message: str, params: dict) -> Dict[str, Any]:
        """对话：解析简历"""
        # 尝试从用户消息中提取文件路径
        file_match = re.search(r'([^\s]+\.(pdf|docx|md|txt))', user_message, re.I)

        resume_file = params.get("resume_file", "")
        if not resume_file and file_match:
            resume_file = file_match.group(1)

        if not resume_file:
            return {
                "status": "success",
                "type": "chat",
                "reply": "请告诉我简历文件的完整路径，例如：\n/Users/name/Desktop/resume.pdf"
            }

        if not os.path.exists(resume_file):
            return {
                "status": "success",
                "type": "chat",
                "reply": f"找不到文件: {resume_file}\n请确认路径是否正确。"
            }

        # 执行解析
        result = await self.execute({"resume_file": resume_file})

        if result.get("status") == "success":
            return {
                "status": "success",
                "type": "action",
                "action": "parse_resume",
                "result": result,
                "reply": "✅ 简历解析成功！我看到了您的工作经历、技能和教育背景。接下来您可以：\n- 提供 JD 让我分析职位匹配度\n- 或者直接让我生成优化建议！"
            }
        else:
            return {
                "status": "success",
                "type": "chat",
                "reply": f"简历解析失败: {result.get('error', '未知错误')}"
            }

    async def _chat_analyze_jd(self, user_message: str, params: dict) -> Dict[str, Any]:
        """对话：分析JD"""
        jd_text = params.get("jd_text", "")
        jd_url = params.get("jd_url", "")

        # 如果没提取到，检查用户输入是否是 URL 或 长文本
        if not jd_url and not jd_text:
            if "http" in user_message:
                jd_url = user_message.strip()
            elif len(user_message) > 50:
                jd_text = user_message

        if not jd_url and not jd_text:
            return {
                "status": "success",
                "type": "chat",
                "reply": "请把职位描述（JD）粘贴给我，或者提供职位链接！"
            }

        input_data = {}
        if jd_url:
            input_data["jd_url"] = jd_url
        else:
            input_data["jd_text"] = jd_text

        result = await self.execute(input_data)

        if result.get("status") == "success":
            reply = "✅ JD 分析完成！我提取了职位要求、技能需求和公司信息。"
            if "resume_data" in self.state:
                reply += "\n现在我可以分析您的简历与这个职位的匹配度！要继续吗？"
            else:
                reply += "\n接下来请提供您的简历，让我分析匹配度！"

            return {
                "status": "success",
                "type": "action",
                "action": "analyze_jd",
                "result": result,
                "reply": reply
            }
        else:
            return {
                "status": "success",
                "type": "chat",
                "reply": f"JD 分析失败: {result.get('error', '未知错误')}"
            }

    async def _chat_run_workflow(self, params: dict) -> Dict[str, Any]:
        """对话：运行完整工作流"""
        has_resume = "resume_data" in self.state
        has_jd = "jd_result" in self.state

        if not has_resume or not has_jd:
            missing = []
            if not has_resume:
                missing.append("简历")
            if not has_jd:
                missing.append("JD")
            return {
                "status": "success",
                "type": "chat",
                "reply": f"还需要提供：{' 和 '.join(missing)}\n请先让我解析简历和分析JD！"
            }

        company_name = params.get("company_name", "目标公司")

        result = await self.execute({"company_name": company_name})

        if result.get("status") == "success":
            return {
                "status": "success",
                "type": "action",
                "action": "run_workflow",
                "result": result,
                "reply": "✅ 工作流完成！我已经为您生成了：\n- 优化后的简历\n- 定制化的 Cover Letter\n- 匹配度分析报告\n您可以在 data/output/ 目录查看输出文件！"
            }
        else:
            return {
                "status": "success",
                "type": "chat",
                "reply": f"工作流执行失败: {result.get('error', '未知错误')}"
            }

    async def _chat_check_state(self) -> Dict[str, Any]:
        """对话：检查状态（给出详细分析）"""
        state = self.state
        reply_parts = []

        # 有匹配度分析结果时，给出详细分析
        if "match_result" in state and "jd_result" in state and "resume_data" in state:
            match_result = state.get("match_result", {})
            score = match_result.get("match_score", 0)

            reply_parts.append(f"📊 当前匹配度: {score}%")

            # 获取简历和JD的关键信息
            resume_data = state.get("resume_data", {})
            jd_result = state.get("jd_result", {})

            header = resume_data.get("header", {})
            name = header.get("name", "候选人")
            resume_skills = resume_data.get("skills", {}).get("technical", [])
            jd_keywords = jd_result.get("keywords", [])
            core_requirements = jd_result.get("core_requirements", [])

            if score >= 70:
                reply_parts.append(f"🎉 {name}，您的简历与这个职位匹配度很高！")
                if resume_skills and jd_keywords:
                    matched = [s for s in resume_skills if any(k.lower() in s.lower() for k in jd_keywords)]
                    if matched:
                        reply_parts.append(f"✅ 匹配技能: {', '.join(matched[:5])}")
            elif score >= 50:
                reply_parts.append(f"🤝 {name}，您的简历与这个职位基本匹配，还有优化空间。")
            else:
                reply_parts.append(f"💡 {name}，您的简历与这个职位匹配度较低，我可以帮您优化！")

            # 列出JD的核心要求
            if core_requirements:
                reply_parts.append("\n📋 职位核心要求:")
                for i, req in enumerate(core_requirements[:5], 1):
                    reply_parts.append(f"  {i}. {req}")

            # 建议下一步
            if score < 70:
                reply_parts.append("\n🚀 建议:")
                reply_parts.append("  - 让我为您生成优化建议")
                reply_parts.append("  - 或者直接让我帮您重写简历！")

        # 只有简历的情况
        elif "resume_data" in state and "jd_result" not in state:
            resume_data = state.get("resume_data", {})
            header = resume_data.get("header", {})
            name = header.get("name", "候选人")
            reply_parts.append(f"✅ {name}，您的简历已解析成功！")
            reply_parts.append("接下来请提供职位描述 (JD)，让我分析匹配度！")

        # 只有JD的情况
        elif "jd_result" in state and "resume_data" not in state:
            jd_result = state.get("jd_result", {})
            title = jd_result.get("title", "职位")
            company = jd_result.get("company", "公司")
            reply_parts.append(f"✅ {company} 的 {title} 职位已分析！")
            reply_parts.append("接下来请提供您的简历，让我分析匹配度！")

        # 没有数据的情况
        else:
            reply_parts.append("目前还没有处理任何数据。")
            reply_parts.append("您可以先让我解析简历或分析职位描述！")

        reply = "\n".join(reply_parts)

        return {
            "status": "success",
            "type": "state",
            "state": dict(state),
            "reply": reply
        }

    async def _chat_response(self, user_message: str, intent: str) -> Dict[str, Any]:
        """对话：纯回复"""
        state_summary = self._get_state_summary()

        prompt = f"""你是 Job Hunter Agent，一个友好专业的求职助手。

当前状态:
{state_summary}

用户说: "{user_message}"
理解的意图: "{intent}"

请给出友好、专业的回复。回复要简短（2-4句话），有帮助性。如果用户需要提供更多信息，请具体说明需要什么。"""

        messages = [LLMMessage(role="user", content=prompt)]
        response = await self.llm_client.analyze(messages, max_tokens=500)

        return {
            "status": "success",
            "type": "chat",
            "reply": response.content.strip()
        }
