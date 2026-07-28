"""Coordinator main orchestrator.

`CoordinatorAgent` 主类 — 组合 CoordinatorToolsMixin / CoordinatorStateMixin /
CoordinatorMatchAnalysisMixin / CoordinatorChatMixin。保留 __init__ / register_tool /
注册工具 / execute() / plan() / 反思与恢复钩子 / 投递相关 wrap（apply stats/history/platforms）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger

from agents.base import BaseAgent, AgentPlan
from core.cache import Cache
from tools.generator.cover_letter_generator import CoverLetterGenerator
from tools.generator.resume_generator import ResumeGenerator
from tools.llm import OpenAICompatibleClient
from tools.resume_parser import ResumeParser
from tools.scraper.auto_submitter import AutoSubmitter
from tools.scraper.jd_analyzer_enhanced import JDAnalyzerEnhanced

from agents.coordinator.chat import CoordinatorChatMixin
from agents.coordinator.match_analysis import CoordinatorMatchAnalysisMixin
from agents.coordinator.state import CoordinatorStateMixin
from agents.coordinator.tools import CoordinatorToolsMixin


class CoordinatorAgent(
    BaseAgent,
    CoordinatorToolsMixin,
    CoordinatorStateMixin,
    CoordinatorMatchAnalysisMixin,
    CoordinatorChatMixin,
):
    """
    协调者 Agent - 单 Agent 调用 Tools 模式

    功能：
    1. 解析简历（ResumeParser）
    2. 分析 JD（JDAnalyzerEnhanced）
    3. 匹配度分析
    4. 生成优化建议
    5. 生成简历（ResumeGenerator）
    6. 生成求职信（CoverLetterGenerator）
    7. 投递决策
    """

    def __init__(self, llm_client: OpenAICompatibleClient, cache: Optional[Cache] = None):
        """
        初始化协调者 Agent

        Args:
            llm_client: LLM 客户端
            cache: 缓存实例（可选）
        """
        super().__init__("coordinator")
        self.llm_client = llm_client
        self.cache = cache or Cache("data/coordinator_cache")

        # 初始化工具模块
        self.resume_parser = ResumeParser()
        self.jd_analyzer = JDAnalyzerEnhanced(llm_client=llm_client)
        self.resume_generator = ResumeGenerator()
        self.cover_letter_generator = CoverLetterGenerator(llm_client=llm_client)
        self.auto_submitter = AutoSubmitter()

        # 工作流状态记忆
        self.workflow_state: Dict[str, Any] = {}
        self.current_step = 0

        # 历史记录记忆
        self.execution_history: List[Dict[str, Any]] = []

        # 注册工具
        self._register_coordinator_tools()

    def _register_coordinator_tools(self):
        """注册协调者工具"""
        self.register_tool(
            "parse_resume",
            "解析简历",
            self._tool_parse_resume
        )
        self.register_tool(
            "analyze_jd",
            "分析职位描述",
            self._tool_analyze_jd
        )
        self.register_tool(
            "analyze_match",
            "分析匹配度",
            self._tool_analyze_match
        )
        self.register_tool(
            "generate_optimization",
            "生成优化建议",
            self._tool_generate_optimization
        )
        self.register_tool(
            "generate_resume",
            "生成简历",
            self._tool_generate_resume
        )
        self.register_tool(
            "generate_cover_letter",
            "生成求职信",
            self._tool_generate_cover_letter
        )
        self.register_tool(
            "submit_application",
            "投递职位",
            self._tool_submit_application
        )
        self.register_tool(
            "batch_submit",
            "批量投递",
            self._tool_batch_submit
        )
        self.register_tool(
            "evaluate_workflow",
            "评估工作流质量",
            self._tool_evaluate_workflow
        )

    async def plan(self, goal: str, input_data: Dict[str, Any]) -> AgentPlan:
        """
        动态规划工作流 - 规划能力

        根据输入动态调整工作流策略
        """
        plan = AgentPlan(goal)

        # 检查输入类型
        has_resume_file = "resume_file" in input_data
        has_jd_text = "jd_text" in input_data

        # 基础步骤
        if has_resume_file:
            plan.add_step(
                "parse_resume", "parse_resume",
                {"input_data": input_data},
                "解析简历"
            )

        if has_jd_text:
            plan.add_step(
                "analyze_jd", "analyze_jd",
                {"input_data": input_data},
                "分析职位描述",
                depends_on=[0] if has_resume_file else []
            )

        # 匹配度分析
        depends_match = []
        if has_resume_file and has_jd_text:
            depends_match = [0, 1]
        elif has_resume_file:
            depends_match = [0]
        plan.add_step(
            "analyze_match", "analyze_match",
            {},
            "分析简历与职位匹配度",
            depends_on=depends_match
        )

        # 生成优化建议
        plan.add_step(
            "generate_optimization", "generate_optimization",
            {},
            "生成简历优化建议",
            depends_on=[2]
        )

        # 生成简历
        plan.add_step(
            "generate_resume", "generate_resume",
            {},
            "生成优化后简历",
            depends_on=[3]
        )

        # 生成求职信
        plan.add_step(
            "generate_cover_letter", "generate_cover_letter",
            {},
            "生成求职信",
            depends_on=[2, 4]
        )

        # 评估工作流质量
        plan.add_step(
            "evaluate_workflow", "evaluate_workflow",
            {},
            "评估工作流质量",
            depends_on=[5]
        )

        return plan

    def _get_goal(self, input_data: Dict[str, Any]) -> str:
        """获取目标"""
        return "职位申请工作流"

    async def _evaluate_step_result(self, step: Dict, result: Any) -> float:
        """评估步骤结果质量"""
        if isinstance(result, dict):
            return 1.0 if result.get("status") == "success" else 0.0
        return 1.0

    async def _correct_result(self, step: Dict, result: Any, quality: float) -> Any:
        """修正结果"""
        return result

    async def _recover_from_failure(self, step: Dict, error: Exception, results: Dict) -> Optional[Dict]:
        """从失败中恢复 - 错误恢复"""
        step_name = step.get("name")
        self.logger.info(f"尝试恢复步骤 {step_name}")

        if step_name == "parse_resume":
            return {"status": "success", "resume_data": None}
        elif step_name == "analyze_jd":
            return {"status": "success", "jd_result": None}

        return None

    async def _reflect_on_execution(self, results: Dict):
        """对执行过程进行反思 - 反思能力"""
        reflection = {
            "timestamp": datetime.now().isoformat(),
            "agent": self.name,
            "steps_completed": len(results),
            "reasoning": self.reasoning
        }

        self.execution_history.append(reflection)
        self.state["last_reflection"] = reflection
        self.save_state()

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行完整工作流

        Args:
            input_data: 输入数据，应包含：
                - resume_file: 简历文件路径（可选）
                - resume_text: 简历文本（可选）
                - jd_text: JD 文本（可选）
                - jd_url: JD URL（可选）

        Returns:
            执行结果
        """
        self.log_action("start_workflow", input_data)

        try:
            self.state["original_input"] = input_data
            self.workflow_state = {
                "start_time": datetime.now().isoformat(),
                "steps": []
            }
            self.current_step = 0
            step_results = {}

            # 检查是否已有预设置的 resume_data
            resume_data = self.state.get("resume_data")
            jd_result = None

            # 步骤 1: 解析简历（仅当没有预设置 resume_data 时）
            if not resume_data and ("resume_file" in input_data or "resume_text" in input_data):
                self._update_progress("正在解析简历...", 1)
                parse_result = await self._step_parse_resume(input_data)
                step_results["parse_resume"] = parse_result
                if parse_result.get("status") == "success":
                    resume_data = parse_result.get("resume_data")
                    self.state["resume_data"] = resume_data

            # 步骤 2: 分析 JD
            if "jd_text" in input_data or "jd_url" in input_data:
                self._update_progress("正在分析职位描述...", 2)
                jd_parse_result = await self._step_analyze_jd(input_data)
                step_results["analyze_jd"] = jd_parse_result
                if jd_parse_result.get("status") == "success":
                    jd_result = jd_parse_result.get("jd_result")
                    self.state["jd_result"] = jd_result

            # 步骤 3: 匹配度分析
            if resume_data and jd_result:
                self._update_progress("正在分析匹配度...", 3)
                match_result = await self._step_analyze_match()
                step_results["analyze_match"] = match_result
                if match_result.get("status") == "success":
                    self.state["match_result"] = match_result.get("match_result")

            # 步骤 4: 生成优化建议
            if resume_data and jd_result:
                self._update_progress("正在生成优化建议...", 4)
                opt_result = await self._step_generate_optimization()
                step_results["generate_optimization"] = opt_result
                if opt_result.get("status") == "success":
                    self.state["optimization_result"] = opt_result.get("optimization_result")

            # 步骤 5: 生成简历
            if resume_data:
                self._update_progress("正在生成优化后简历...", 5)
                resume_gen_result = await self._step_generate_resume()
                step_results["generate_resume"] = resume_gen_result

            # 步骤 6: 生成求职信
            if resume_data and jd_result:
                self._update_progress("正在生成求职信...", 6)
                cl_gen_result = await self._step_generate_cover_letter()
                step_results["generate_cover_letter"] = cl_gen_result

            # 反思执行过程
            self.state["step_results"] = step_results
            await self._reflect_on_execution(step_results)

            self._update_progress("工作流完成", 6)

            final_result = self._build_success_result({
                "resume_data": resume_data,
                "jd_result": jd_result,
                "match_result": self.state.get("match_result"),
                "optimization_result": self.state.get("optimization_result"),
                "step_results": step_results,
                "summary": self._generate_summary(resume_data, jd_result, self.state.get("match_result"))
            })

            return final_result

        except Exception as e:
            self.logger.exception(f"工作流执行失败: {e}")
            return {
                "status": "error",
                "error": str(e),
                "agent": self.name
            }

    async def _step_parse_resume(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """步骤：解析简历"""
        self.current_step += 1
        return await self._tool_parse_resume(input_data)

    async def _step_analyze_jd(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """步骤：分析 JD"""
        self.current_step += 1
        return await self._tool_analyze_jd(input_data)

    async def _step_analyze_match(self) -> Dict[str, Any]:
        """步骤：分析匹配度"""
        self.current_step += 1
        return await self._tool_analyze_match()

    async def _step_generate_optimization(self) -> Dict[str, Any]:
        """步骤：生成优化建议"""
        self.current_step += 1
        return await self._tool_generate_optimization()

    async def _step_generate_resume(self) -> Dict[str, Any]:
        """步骤：生成简历"""
        self.current_step += 1
        return await self._tool_generate_resume()

    async def _step_generate_cover_letter(self) -> Dict[str, Any]:
        """步骤：生成求职信"""
        self.current_step += 1
        return await self._tool_generate_cover_letter()

    # ============================================================
    # AutoSubmitter 透传 (历史 API 兼容)
    # ============================================================

    def get_application_stats(self) -> Dict[str, Any]:
        """获取投递统计"""
        return self.auto_submitter.get_stats()

    def get_application_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """获取投递历史"""
        return self.auto_submitter.get_application_history(limit)

    def get_supported_platforms(self) -> List[str]:
        """获取支持的平台列表"""
        return self.auto_submitter.get_supported_platforms()
