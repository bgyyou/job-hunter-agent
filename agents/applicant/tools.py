"""Applicant tools: _tool_filter_jobs / _tool_apply_single_job / _tool_batch_apply /
_tool_evaluate_application_quality / _tool_evaluate_filter_result /
_apply_strategy_with_mode / _register_applicant_tools / plan / _analyze_match_distribution / _get_goal.

原 applicant.py 行 62-407 整体迁移。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from agents.base import AgentPlan
from loguru import logger

from models.application import ApplicationStatus


class ApplicantToolsMixin:
    """Tool + plan mixin. Expects self.state / self.logger / self.start_span / self.end_span /
    self.application_stats / self.application_history."""

    def _register_applicant_tools(self) -> None:
        """注册投递工具"""
        self.register_tool(
            "filter_jobs",
            "过滤符合条件的职位",
            self._tool_filter_jobs
        )
        self.register_tool(
            "apply_single_job",
            "投递单个职位",
            self._tool_apply_single_job
        )
        self.register_tool(
            "batch_apply",
            "批量投递职位",
            self._tool_batch_apply
        )
        self.register_tool(
            "evaluate_application_quality",
            "评估投递质量",
            self._tool_evaluate_application_quality
        )

    async def plan(self, goal: str, input_data: Dict[str, Any]) -> AgentPlan:
        """
        动态规划投递策略 - 规划能力

        根据匹配度分布动态调整投递策略
        """
        plan = AgentPlan(goal)

        matches = input_data.get("matches", [])
        auto_confirm = input_data.get("auto_confirm", self.auto_confirm)

        # 分析匹配度分布
        strategy = self._analyze_match_distribution(matches)

        # 步骤：过滤符合条件的职位
        plan.add_step(
            "filter_jobs", "filter_jobs",
            {"strategy": strategy},
            "根据匹配度过滤职位"
        )

        # 步骤：评估过滤结果
        plan.add_step(
            "evaluate_filter_result", "evaluate_filter_result",
            {},
            "评估过滤结果",
            depends_on=[0]
        )

        if auto_confirm:
            # 自动模式：批量投递
            plan.add_step(
                "batch_apply", "batch_apply",
                {},
                "批量投递职位",
                depends_on=[1]
            )
        else:
            # 手动模式：准备待确认列表
            plan.add_step(
                "prepare_confirmation", "prepare_confirmation",
                {},
                "准备待确认列表",
                depends_on=[1]
            )

        # 步骤：评估投递质量
        plan.add_step(
            "evaluate_application_quality", "evaluate_application_quality",
            {},
            "评估投递质量",
            depends_on=[i for i, s in enumerate([0, 1, 2]) if plan.steps[i]["name"] != "evaluate_application_quality"]
        )

        return plan

    def _analyze_match_distribution(self, matches: List[Dict[str, Any]]) -> str:
        """分析匹配度分布，决定投递策略"""
        if not matches:
            return "conservative"

        scores = [m.get("score", 0) for m in matches]
        avg_score = sum(scores) / len(scores) if scores else 0
        high_match = sum(1 for s in scores if s >= 85)

        # 根据历史投递成功率调整策略
        if self.application_stats.get("total_applied", 0) > 5:
            success_rate = self.application_stats["success_count"] / self.application_stats["total_applied"]
            if success_rate < 0.5:
                self.logger.info("历史投递成功率低，使用保守策略")
                return "conservative"

        # 根据当前匹配度选择策略
        if avg_score >= 80 and high_match >= len(matches) * 0.5:
            return "aggressive"
        elif avg_score >= 70:
            return "balanced"
        else:
            return "conservative"

    def _get_goal(self, input_data: Dict[str, Any]) -> str:
        """获取目标"""
        auto_confirm = input_data.get("auto_confirm", self.auto_confirm)
        mode = "自动" if auto_confirm else "手动"
        return f"投递符合条件的职位（{mode}确认模式）"

    # ============================================================
    # 工具实现
    # ============================================================

    async def _tool_filter_jobs(
        self,
        strategy: str = "balanced",
    ) -> Dict[str, Any]:
        """工具：过滤符合条件的职位"""
        span = self.start_span("tool:filter_jobs")

        try:
            matches = self.state.get("matches", [])

            # 按匹配度排序
            sorted_matches = sorted(
                matches,
                key=lambda x: x.get("score", 0),
                reverse=True
            )

            # 应用策略
            qualified_matches = self._apply_strategy_with_mode(
                sorted_matches, strategy
            )

            # 保存到状态
            self.state["filtered_jobs"] = qualified_matches

            if span:
                self.end_span(True)

            return {
                "status": "success",
                "jobs": qualified_matches,
                "strategy": strategy,
                "count": len(qualified_matches)
            }

        except Exception as e:
            self.logger.error(f"过滤职位失败: {e}")
            if span:
                self.end_span(False, str(e))
            return {"status": "error", "error": str(e)}

    async def _tool_apply_single_job(self, job: Dict[str, Any]) -> Dict[str, Any]:
        """工具：投递单个职位"""
        from datetime import datetime as _dt
        from models.application import ApplicationRecord, ApplicationMethod

        span = self.start_span("tool:apply_single_job")

        try:
            platform = job.get("platform", "boss")

            if platform not in self.scrapers:
                self.logger.warning(f"不支持的平台: {platform}")
                return {"status": "error", "error": f"不支持的平台: {platform}"}

            scraper = self.scrapers[platform]

            # 模拟投递
            success = await self._mock_apply(scraper, job)

            # 创建投递记录
            if success:
                record = ApplicationRecord(
                    job_id=job.get("job_id", ""),
                    resume_version="v1.0",
                    applied_at=_dt.now(),
                    status=ApplicationStatus.SUBMITTED,
                    method=ApplicationMethod.AUTO
                )
            else:
                record = ApplicationRecord(
                    job_id=job.get("job_id", ""),
                    resume_version="v1.0",
                    status=ApplicationStatus.FAILED,
                    method=ApplicationMethod.AUTO,
                    error="登录失败或网络错误"
                )

            # 更新统计
            self.application_stats["total_applied"] += 1
            if success:
                self.application_stats["success_count"] += 1
            else:
                self.application_stats["failed_count"] += 1

            # 更新平均匹配度
            current_avg = self.application_stats["avg_match_score"]
            total = self.application_stats["total_applied"]
            new_score = job.get("score", 0)
            self.application_stats["avg_match_score"] = (current_avg * (total - 1) + new_score) / total

            if span:
                self.end_span(success)

            return {
                "status": "success" if success else "failed",
                "record": record.model_dump()
            }

        except Exception as e:
            self.logger.error(f"投递职位失败 {job.get('job_id')}: {e}")
            if span:
                self.end_span(False, str(e))
            return {"status": "error", "error": str(e)}

    async def _tool_batch_apply(self) -> Dict[str, Any]:
        """工具：批量投递职位"""
        span = self.start_span("tool:batch_apply")

        try:
            jobs = self.state.get("filtered_jobs", [])
            max_applications = self.state.get("max_applications", 10)

            # 限制数量
            jobs = jobs[:max_applications]

            if not jobs:
                return {
                    "status": "success",
                    "applications": [],
                    "count": 0
                }

            # 批量投递
            applications = await self._apply_jobs(jobs)

            if span:
                success_count = sum(1 for a in applications if a.status == ApplicationStatus.SUBMITTED)
                self.end_span(success_count > 0)

            return {
                "status": "success",
                "applications": [a.model_dump() for a in applications],
                "count": len(applications)
            }

        except Exception as e:
            self.logger.error(f"批量投递失败: {e}")
            if span:
                self.end_span(False, str(e))
            return {"status": "error", "error": str(e)}

    async def _tool_evaluate_application_quality(self) -> Dict[str, Any]:
        """工具：评估投递质量 - 反思能力"""
        applications = self.state.get("applications", [])

        evaluation = {
            "total_applications": len(applications),
            "success_rate": 0.0,
            "avg_match_score": 0.0,
            "quality_score": 0.8,
            "issues": []
        }

        if applications:
            # 成功率
            success_count = sum(1 for a in applications if a.get("status") == "SUBMITTED")
            evaluation["success_rate"] = success_count / len(applications)

            # 平均匹配度（从历史记录）
            if self.application_history:
                recent_scores = [h.get("match_score", 0) for h in self.application_history[-len(applications):]]
                evaluation["avg_match_score"] = sum(recent_scores) / len(recent_scores) if recent_scores else 0

            # 质量评分
            if evaluation["success_rate"] >= 0.8:
                evaluation["quality_score"] = 1.0
            elif evaluation["success_rate"] >= 0.5:
                evaluation["quality_score"] = 0.8
            else:
                evaluation["quality_score"] = 0.5
                evaluation["issues"].append("投递成功率偏低")

        # 从统计中获取整体质量
        total = self.application_stats.get("total_applied", 0)
        if total > 0:
            overall_success_rate = self.application_stats["success_count"] / total
            evaluation["overall_success_rate"] = overall_success_rate

        self.logger.info(f"投递质量评估: {evaluation}")

        return {"status": "success", "evaluation": evaluation}

    async def _tool_evaluate_filter_result(self) -> Dict[str, Any]:
        """工具：评估过滤结果"""
        filtered = self.state.get("filtered_jobs", [])

        evaluation = {
            "filtered_count": len(filtered),
            "sufficient": len(filtered) >= 3,
            "needs_more": len(filtered) < 3
        }

        if len(filtered) == 0:
            self.logger.info("没有符合条件的职位")
        elif len(filtered) < 3:
            self.logger.info(f"符合条件的职位较少({len(filtered)})")

        return {"status": "success", "evaluation": evaluation}

    def _apply_strategy_with_mode(
        self,
        matches: List[Dict[str, Any]],
        strategy: str,
    ) -> List[Dict[str, Any]]:
        """
        应用投递策略

        Args:
            matches: 匹配结果列表
            strategy: 策略模式 (aggressive/balanced/conservative)

        Returns:
            符合条件的职位列表
        """
        qualified = []

        for match in matches:
            score = match.get("score", 0)

            if strategy == "aggressive":
                if score >= 65:
                    qualified.append(match)
            elif strategy == "balanced":
                if score >= 70:
                    qualified.append(match)
            else:  # conservative
                if score >= 75:
                    qualified.append(match)

        self.logger.info(f"策略 {strategy}: {len(qualified)}/{len(matches)} 职位符合条件")

        return qualified
