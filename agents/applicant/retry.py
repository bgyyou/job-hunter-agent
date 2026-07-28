"""Applicant retry / recovery / reflection / correction helpers.

从原 applicant.py 行 410-472 整体迁移：
_evaluate_step_result / _correct_result / _recover_from_failure / _reflect_on_execution。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional


class ApplicantRetryMixin:
    """Reflection + correction + recovery mixin. Expects self.state / self.name / self.reasoning."""

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
