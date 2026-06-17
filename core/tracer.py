# core/tracer.py
from typing import Dict, List, Optional
from datetime import datetime
import json


class AgentSpan:
    """Agent 调用的一个 span"""

    def __init__(self, agent: str, operation: str):
        self.agent = agent
        self.operation = operation
        self.start_time = datetime.now()
        self.end_time: Optional[datetime] = None
        self.parent_span: Optional['AgentSpan'] = None
        self.status = "running"
        self.error: Optional[str] = None
        self.duration: Optional[float] = None

    def end(self, success: bool = True, error: Optional[str] = None):
        """结束 span"""
        self.end_time = datetime.now()
        self.duration = (self.end_time - self.start_time).total_seconds()
        self.status = "success" if success else "error"
        self.error = error

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "agent": self.agent,
            "operation": self.operation,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "status": self.status,
            "duration": self.duration,
            "error": self.error
        }


class AgentTracer:
    """链路追踪 - 错误定位"""

    def __init__(self):
        self.spans: List[AgentSpan] = []
        self.current_span: Optional[AgentSpan] = None

    def start_span(self, agent_name: str, operation: str) -> AgentSpan:
        """
        开始一个 span

        Args:
            agent_name: Agent 名称
            operation: 操作名称

        Returns:
            Span 对象
        """
        span = AgentSpan(agent_name, operation)
        span.parent_span = self.current_span
        self.spans.append(span)
        self.current_span = span
        return span

    def end_span(self, success: bool = True, error: Optional[str] = None):
        """
        结束当前 span

        Args:
            success: 是否成功
            error: 错误信息
        """
        if self.current_span:
            self.current_span.end(success, error)
            self.current_span = self.current_span.parent_span

    def get_error_chain(self) -> List[Dict]:
        """
        获取错误链路

        Returns:
            错误 span 列表
        """
        return [
            span.to_dict()
            for span in self.spans
            if span.status == "error"
        ]

    def get_span(self, agent: str, operation: str) -> Optional[AgentSpan]:
        """
        获取指定的 span

        Args:
            agent: Agent 名称
            operation: 操作名称

        Returns:
            Span 对象或 None
        """
        for span in self.spans:
            if span.agent == agent and span.operation == operation:
                return span
        return None

    def visualize(self) -> str:
        """
        可视化调用链

        Returns:
            可视化字符串
        """
        output = ["\n调用链:"]

        for span in self.spans:
            indent = "  " * self._get_depth(span)
            status = "✅" if span.status == "success" else "❌"
            duration = f" ({span.duration:.2f}s)" if span.duration else ""
            output.append(f"{indent}{status} {span.agent}.{span.operation}{duration}")

            if span.error:
                output.append(f"{indent}   错误: {span.error}")

        return "\n".join(output)

    def _get_depth(self, span: AgentSpan) -> int:
        """获取 span 深度"""
        depth = 0
        parent = span.parent_span
        while parent:
            depth += 1
            parent = parent.parent_span
        return depth

    def clear(self):
        """清除所有 span"""
        self.spans.clear()
        self.current_span = None

    def export(self, filepath: str):
        """
        导出追踪记录到文件

        Args:
            filepath: 文件路径
        """
        data = {
            "timestamp": datetime.now().isoformat(),
            "spans": [span.to_dict() for span in self.spans]
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)