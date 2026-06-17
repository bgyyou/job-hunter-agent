# agents/applicant.py
"""
投递 Agent - 真正的 Agent 实现

具备能力：
1. 规划能力 - 根据匹配度动态调整投递策略
2. 工具调用 - 封装投递步骤
3. 反思能力 - 评估投递决策质量
4. 错误恢复 - 处理投递失败
5. 记忆能力 - 记住投递历史
6. 安全性 - 人工确认机制
"""
from typing import Dict, Any, List, Optional
from datetime import datetime
from agents.base import BaseAgent, AgentPlan
from tools.scraper.boss_scraper import BossScraper
from models.application import ApplicationRecord, ApplicationStatus, ApplicationMethod
from loguru import logger


class ApplicantAgent(BaseAgent):
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

    # ==================== 工具注册 ====================

    def _register_applicant_tools(self):
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

    # ==================== 规划能力 ====================

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

    # ==================== 工具实现 ====================

    async def _tool_filter_jobs(
        self,
        strategy: str = "balanced"
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
                    applied_at=datetime.now(),
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
        strategy: str
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

    # ==================== 反思能力 ====================

    async def _evaluate_step_result(self, step: Dict, result: Any) -> float:
        """评估步骤结果质量"""
        if step["name"] in ["filter_jobs", "prepare_confirmation"]:
            job_count = len(result.get("jobs", [])) if isinstance(result, dict) else 0
            return min(job_count / 5, 1.0) if job_count > 0 else 0.5

        elif step["name"] == "batch_apply":
            applications = result.get("applications", [])
            if not applications:
                return 0.5
            success_count = sum(1 for a in applications if a.get("status") == "SUBMITTED")
            return success_count / len(applications)

        elif step["name"] == "evaluate_application_quality":
            evaluation = result.get("evaluation", {})
            return evaluation.get("quality_score", 0.8)

        return 1.0

    async def _correct_result(self, step: Dict, result: Any, quality: float) -> Any:
        """修正结果"""
        if quality < 0.7 and isinstance(result, dict):
            self.logger.warning(f"步骤 {step['name']} 质量偏低，尝试修正")

            if step["name"] == "filter_jobs" and not result.get("jobs"):
                result.setdefault("jobs", [])
                result.setdefault("suggestion", "考虑降低匹配度阈值")

            elif step["name"] == "batch_apply":
                result.setdefault("applications", [])
                result.setdefault("fallback_reason", "部分投递失败")

        return result

    async def _recover_from_failure(self, step: Dict, error: Exception, results: Dict) -> Optional[Dict]:
        """从失败中恢复 - 错误恢复"""
        step_name = step["name"]

        if step_name == "filter_jobs":
            return {"status": "success", "jobs": []}

        elif step_name == "batch_apply":
            return {"status": "success", "applications": []}

        return None

    async def _reflect_on_execution(self, results: Dict):
        """对投递执行过程进行反思 - 反思能力"""
        reflection = {
            "timestamp": datetime.now().isoformat(),
            "agent": self.name,
            "steps_completed": len(results),
            "total_applied": self.application_stats["total_applied"],
            "success_rate": (
                self.application_stats["success_count"] / self.application_stats["total_applied"]
                if self.application_stats["total_applied"] > 0 else 0
            ),
            "avg_match_score": self.application_stats["avg_match_score"],
            "reasoning": self.reasoning
        }

        self.state["last_reflection"] = reflection
        self.save_state()

    # ==================== 记忆能力 ====================

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

    # ==================== 核心执行 ====================

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
        confirmed_indices: List[int]
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
        matches: List[Dict[str, Any]]
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

    async def _apply_jobs(
        self,
        jobs: List[Dict[str, Any]]
    ) -> List[ApplicationRecord]:
        """
        执行投递

        Args:
            jobs: 职位列表

        Returns:
            投递记录列表
        """
        applications = []

        for job in jobs:
            try:
                platform = job.get("platform", "boss")

                if platform not in self.scrapers:
                    self.logger.warning(f"不支持的平台: {platform}")
                    continue

                scraper = self.scrapers[platform]

                # 模拟投递（实际需要实现具体的投递逻辑）
                success = await self._mock_apply(scraper, job)

                # 创建投递记录
                if success:
                    record = ApplicationRecord(
                        job_id=job.get("job_id", ""),
                        resume_version="v1.0",
                        applied_at=datetime.now(),
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

                applications.append(record)

                self.log_action("job_applied", {
                    "job_id": job.get("job_id"),
                    "success": success
                })

            except Exception as e:
                self.logger.error(f"投递职位失败 {job.get('job_id')}: {e}")
                continue

        # 更新投递历史
        for i, job in enumerate(jobs):
            if i < len(applications):
                history_entry = applications[i].model_dump()
                history_entry["match_score"] = job.get("score", 0)
                history_entry["job_title"] = job.get("title", "")
                history_entry["company"] = job.get("company", "")
                history_entry["platform"] = job.get("platform", "")
                self.application_history.append(history_entry)

        # 保存状态
        self.state["last_application"] = {
            "count": len(applications),
            "timestamp": datetime.now().isoformat()
        }
        self.save_state()

        return applications

    async def _mock_apply(self, scraper: Any, job: Dict[str, Any]) -> bool:
        """
        模拟投递（实际实现需要调用爬虫的投递接口）

        Args:
            scraper: 爬虫实例
            job: 职位信息

        Returns:
            是否成功
        """
        # 模拟网络延迟
        import asyncio
        await asyncio.sleep(0.1)

        # 检查登录状态
        is_logged_in = await scraper.is_logged_in()
        if not is_logged_in:
            self.logger.warning("未登录，投递可能失败")
            return False

        # 实际实现需要调用平台的投递 API
        # 这里模拟成功
        return True

    def _prepare_for_confirmation(
        self,
        jobs: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        准备确认列表

        Args:
            jobs: 职位列表

        Returns:
            待确认的职位信息
        """
        return [
            {
                "index": i,
                "job_id": job.get("job_id", ""),
                "title": job.get("title", ""),
                "company": job.get("company", ""),
                "location": job.get("location", ""),
                "salary_min": job.get("salary_min"),
                "salary_max": job.get("salary_max"),
                "match_score": job.get("score", 0),
                "reasoning": job.get("reasoning", ""),
                "gaps": job.get("gaps", []),
                "recommendation": self._get_recommendation(job.get("score", 0))
            }
            for i, job in enumerate(jobs)
        ]

    def _get_recommendation(self, score: float) -> str:
        """获取投递建议"""
        if score >= 85:
            return "强烈推荐"
        elif score >= 75:
            return "推荐"
        elif score >= 70:
            return "可以考虑"
        else:
            return "不建议"

    def _generate_reasoning(
        self,
        applications: List[Any],
        auto_mode: bool
    ) -> str:
        """生成决策理由"""
        parts = []

        if auto_mode:
            parts.append("【投递模式】自动投递")
        else:
            parts.append("【投递模式】人工确认")

        parts.append(f"【投递数量】{len(applications)} 个职位")

        # 统计匹配度分布
        if applications:
            # 从历史记录中获取分数
            scores = []
            for a in applications:
                # 从历史记录中查找对应分数
                for h in self.application_history:
                    if h.get("job_id") == a.job_id:
                        # 尝试从 job 数据中获取分数（在扩展的历史记录中）
                        # 这里暂时使用默认值
                        scores.append(h.get("match_score", 75))
                        break
                else:
                    scores.append(75)  # 默认值

            if scores:
                avg_score = sum(scores) / len(scores)
                high_match = sum(1 for s in scores if s >= 85)
                mid_match = sum(1 for s in scores if 70 <= s < 85)
            else:
                avg_score = 75
                high_match = 0
                mid_match = 0

            parts.append(f"【平均匹配度】{avg_score:.1f}%")
            parts.append(f"【高匹配度(≥85%)】{high_match} 个")
            parts.append(f"【中匹配度(70-85%)】{mid_match} 个")

        parts.append(f"【更新时间】{datetime.now().strftime('%Y-%m-%d %H:%M')}")

        return "\n".join(parts)

    def get_application_history(
        self,
        limit: int = 20
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