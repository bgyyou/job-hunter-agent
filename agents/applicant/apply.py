"""Applicant main orchestrator.

`ApplicantAgent` 主类 — 组合 ApplicantToolsMixin + ApplicantSubmitMixin + ApplicantRetryMixin。
保留 __init__ / execute() / confirm_and_apply() / _apply_strategy / get_application_stats /
get_application_history / clear_history / validate_input。
"""
from __future__ import annotations

from typing import Any, Dict, List

from loguru import logger

from agents.applicant.retry import ApplicantRetryMixin
from agents.applicant.submit import ApplicantSubmitMixin
from agents.applicant.tools import ApplicantToolsMixin
from agents.base import BaseAgent
from tools.scraper.boss_scraper import BossScraper


class ApplicantAgent(
    BaseAgent,
    ApplicantToolsMixin,
    ApplicantSubmitMixin,
    ApplicantRetryMixin,
):
    """
    投递 Agent - 真正的 Agent 实现

    功能：
    1. 智能投递策略（基于匹配度）
    2. 人工确认流程（安全性）
    3. 投递状态跟踪
    4. 动态策略调整
    5. 投递质量反思
    """

    def __init__(self, auto_confirm: bool = False):
        """
        初始化投递 Agent

        Args:
            auto_confirm: 是否自动确认（测试用），默认 False 需要人工确认
        """
        super().__init__("applicant")
        self.auto_confirm = auto_confirm

        # 初始化爬虫
        self.scrapers = {
            "boss": BossScraper()
        }

        # 投递历史记忆
        self.application_history: List[Dict[str, Any]] = []

        # 投递统计
        self.application_stats = {
            "total_applied": 0,
            "success_count": 0,
            "failed_count": 0,
            "avg_match_score": 0.0
        }

        # 注册工具
        self._register_applicant_tools()

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行投递

        Args:
            input_data: 输入数据，应包含：
                - matches: 匹配结果列表
                - auto_confirm: 是否自动确认（可选，覆盖初始化设置）
                - max_applications: 最大投递数量（可选，默认 10）

        Returns:
            投递结果，包含：
                - status: 执行状态 (success/pending/error)
                - applications: 投递记录列表
                - total_applied: 成功投递数量
                - pending_confirm: 待确认的职位（非自动模式）
                - reasoning: 决策理由
        """
        self.log_action("start_application", input_data)

        try:
            matches = input_data["matches"]
            auto_confirm = input_data.get("auto_confirm", self.auto_confirm)
            max_applications = input_data.get("max_applications", 10)

            # 保存输入到状态
            self.state["matches"] = matches
            self.state["max_applications"] = max_applications
            self.state["auto_confirm"] = auto_confirm

            # 按匹配度排序
            sorted_matches = sorted(
                matches,
                key=lambda x: x.get("score", 0),
                reverse=True
            )

            # 应用投递策略
            qualified_matches = self._apply_strategy(sorted_matches)

            # 限制投递数量
            qualified_matches = qualified_matches[:max_applications]

            if not qualified_matches:
                reasoning = "没有符合投递条件的职位"
                self.set_reasoning(reasoning)
                return {
                    "status": "success",
                    "applications": [],
                    "total_applied": 0,
                    "reasoning": reasoning
                }

            # 执行投递
            if auto_confirm:
                # 自动模式：直接投递
                applications = await self._apply_jobs(qualified_matches)

                # 保存到状态
                self.state["applications"] = [a.model_dump() for a in applications]

                # 生成决策理由
                reasoning = self._generate_reasoning(applications, auto_mode=True)
                self.set_reasoning(reasoning)

                return {
                    "status": "success",
                    "applications": [a.model_dump() for a in applications],
                    "total_applied": len(applications),
                    "reasoning": reasoning
                }
            else:
                # 人工确认模式：返回待确认列表
                pending = self._prepare_for_confirmation(qualified_matches)

                # 保存到状态
                self.state["pending_confirm"] = pending

                reasoning = self._generate_reasoning(pending, auto_mode=False)
                self.set_reasoning(reasoning)

                return {
                    "status": "pending",
                    "pending_confirm": pending,
                    "total_pending": len(pending),
                    "reasoning": reasoning
                }

        except Exception as e:
            self.logger.error(f"投递失败: {e}")
            return {
                "status": "error",
                "error": str(e),
                "agent": self.name
            }

    async def confirm_and_apply(
        self,
        pending_jobs: List[Dict[str, Any]],
        confirmed_indices: List[int],
    ) -> Dict[str, Any]:
        """
        确认并投递（人工确认模式）

        Args:
            pending_jobs: 待确认的职位列表
            confirmed_indices: 确认的职位索引列表

        Returns:
            投递结果
        """
        self.log_action("confirm_and_apply", {
            "pending": len(pending_jobs),
            "confirmed": len(confirmed_indices)
        })

        try:
            # 获取确认的职位
            confirmed_jobs = []
            for idx in confirmed_indices:
                if 0 <= idx < len(pending_jobs):
                    confirmed_jobs.append(pending_jobs[idx])

            if not confirmed_jobs:
                return {
                    "status": "success",
                    "applications": [],
                    "total_applied": 0,
                    "reasoning": "未选择任何职位投递"
                }

            # 投递
            applications = await self._apply_jobs(confirmed_jobs)

            reasoning = self._generate_reasoning(applications, auto_mode=True)

            return {
                "status": "success",
                "applications": [a.model_dump() for a in applications],
                "total_applied": len(applications),
                "reasoning": reasoning
            }

        except Exception as e:
            self.logger.error(f"确认投递失败: {e}")
            return {
                "status": "error",
                "error": str(e),
                "agent": self.name
            }

    def _apply_strategy(
        self,
        matches: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        应用投递策略（基于匹配度）

        策略规则：
        - 匹配度 ≥ 85%：自动投递
        - 匹配度 70-85%：显示预览，可确认投递
        - 匹配度 < 70%：不投递

        Args:
            matches: 匹配结果列表

        Returns:
            符合条件的职位列表
        """
        qualified = []

        for match in matches:
            score = match.get("score", 0)

            if score >= 70:
                qualified.append(match)
                self.logger.info(f"符合投递条件: score={score}%")
            else:
                self.logger.debug(f"不符合投递条件: score={score}%")

        return qualified

    def get_application_stats(self) -> Dict[str, Any]:
        """获取投递统计"""
        return self.application_stats.copy()

    def clear_history(self):
        """清空历史记录"""
        self.application_history = []
        self.application_stats = {
            "total_applied": 0,
            "success_count": 0,
            "failed_count": 0,
            "avg_match_score": 0.0
        }
        self.logger.info("投递历史已清空")

    def get_application_history(
        self,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """获取投递历史"""
        return self.application_history[-limit:]

    def validate_input(self, input_data: Dict[str, Any]) -> bool:
        """验证输入"""
        if not super().validate_input(input_data):
            return False

        if "matches" not in input_data:
            self.logger.error("缺少匹配结果")
            return False

        if not isinstance(input_data["matches"], list):
            self.logger.error("matches 必须是列表")
            return False

        return True
