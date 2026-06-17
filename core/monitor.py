# core/monitor.py
from typing import Dict, List
from datetime import datetime


class Monitor:
    """监控系统 - 可观测性"""

    def __init__(self):
        self.metrics = {
            "jobs_searched": 0,
            "jobs_matched": 0,
            "jobs_applied": 0,
            "llm_calls": 0,
            "llm_tokens": 0,
            "errors": []
        }
        self.start_time = datetime.now()

    def record_job_searched(self, count: int):
        """记录搜索到的职位数"""
        self.metrics["jobs_searched"] += count

    def record_job_matched(self, count: int):
        """记录匹配的职位数"""
        self.metrics["jobs_matched"] += count

    def record_job_applied(self, count: int):
        """记录投递的职位数"""
        self.metrics["jobs_applied"] += count

    def record_llm_call(self, tokens: int):
        """记录 LLM 调用"""
        self.metrics["llm_calls"] += 1
        self.metrics["llm_tokens"] += tokens

    def record_error(self, error: str, agent: str):
        """记录错误"""
        self.metrics["errors"].append({
            "timestamp": datetime.now().isoformat(),
            "agent": agent,
            "error": error
        })

    def get_report(self) -> Dict:
        """生成监控报告"""
        duration_seconds = (datetime.now() - self.start_time).total_seconds()

        return {
            "timestamp": datetime.now().isoformat(),
            "duration_seconds": duration_seconds,
            **self.metrics,
            "cost_estimate": self._estimate_cost(),
            "jobs_per_second": self.metrics["jobs_matched"] / duration_seconds if duration_seconds > 0 else 0
        }

    def _estimate_cost(self) -> float:
        """
        估算成本

        Returns:
            成本（人民币）
        """
        # Claude 定价（示例）
        input_cost = self.metrics["llm_tokens"] * 0.000003  # $3/M tokens
        output_cost = self.metrics["llm_tokens"] * 0.000015  # $15/M tokens
        usd_cost = input_cost + output_cost

        # 转换为人民币
        return usd_cost * 6.5

    def reset(self):
        """重置监控指标"""
        self.metrics = {
            "jobs_searched": 0,
            "jobs_matched": 0,
            "jobs_applied": 0,
            "llm_calls": 0,
            "llm_tokens": 0,
            "errors": []
        }
        self.start_time = datetime.now()