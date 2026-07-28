"""Coordinator state helpers.

集中 _update_progress / _generate_summary / _build_success_result / _build_error_result /
get_workflow_status / validate_input / get_state_summary / _get_state_summary 等状态相关方法，
供 orchestrator 调用，避免主类无限膨胀。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional


class CoordinatorStateMixin:
    """State-related helpers mixin for CoordinatorAgent."""

    # instance attributes supplied by CoordinatorAgent.__init__:
    # self.workflow_state, self.current_step, self.state, self.reasoning, self.logger

    def _update_progress(self, message: str, step: int) -> None:
        """更新进度"""
        self.set_reasoning(f"【进度】{message}")

    def _generate_summary(
        self,
        resume_data: Any,
        jd_result: Optional[Dict[str, Any]],
        match_result: Optional[Dict[str, Any]],
    ) -> str:
        """生成工作流摘要"""
        parts = []

        if jd_result:
            parts.append(f"【职位】{jd_result.get('title', '未知')} @ {jd_result.get('company', '未知')}")

        if match_result:
            score = match_result.get('score', 0)
            parts.append(f"【匹配度】{score:.1f}%")

        parts.append(f"【完成时间】{datetime.now().strftime('%Y-%m-%d %H:%M')}")

        return "\n".join(parts)

    def _build_success_result(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """构建成功结果"""
        return {
            "status": "success",
            "workflow_summary": data["summary"],
            "resume_data": data["resume_data"],
            "jd_result": data["jd_result"],
            "match_result": data["match_result"],
            "optimization_result": data.get("optimization_result"),
            "step_results": data.get("step_results"),
            "reasoning": self.reasoning,
        }

    def _build_error_result(
        self,
        error_message: str,
        error_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """构建错误结果"""
        return {
            "status": "error",
            "error": error_message,
            "details": error_result,
            "workflow_state": self.workflow_state,
        }

    def get_workflow_status(self) -> Dict[str, Any]:
        """获取当前工作流状态"""
        return {
            "current_step": self.current_step,
            "steps": self.workflow_state.get("steps", []),
            "reasoning": self.reasoning,
        }

    def validate_input(self, input_data: Dict[str, Any]) -> bool:
        """验证输入"""
        if not super().validate_input(input_data):
            return False

        has_resume = "resume_file" in input_data or "resume_text" in input_data
        has_jd = "jd_text" in input_data or "jd_url" in input_data

        if not has_resume and not has_jd:
            self.logger.error("至少需要提供简历或 JD")
            return False

        return True

    def _get_state_summary(self) -> str:
        """获取状态摘要"""
        state = self.state
        has_resume = "resume_data" in state
        has_jd = "jd_result" in state
        has_match = "match_result" in state

        summary = []
        if has_resume:
            summary.append("✅ 已解析简历")
        else:
            summary.append("❌ 未解析简历")

        if has_jd:
            summary.append("✅ 已分析JD")
        else:
            summary.append("❌ 未分析JD")

        if has_match:
            summary.append("✅ 已分析匹配度")

        return "\n".join(summary)
