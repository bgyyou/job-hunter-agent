"""Applicant submit / mock / batch helpers.

从原 applicant.py 行 675-774 + 776-815 + 818-862 整体迁移：
_apply_jobs / _mock_apply / _prepare_for_confirmation / _get_recommendation / _generate_reasoning。
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List

from models.application import ApplicationRecord, ApplicationMethod, ApplicationStatus


class ApplicantSubmitMixin:
    """Submit + mock_apply + batch helpers. Expects self.scrapers / self.application_history / self.application_stats."""

    async def _apply_jobs(
        self,
        jobs: List[Dict[str, Any]],
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
        jobs: List[Dict[str, Any]],
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
        auto_mode: bool,
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
