# protocols/message.py
from pydantic import BaseModel, Field, ConfigDict
from typing import Dict, Any, Optional
from datetime import datetime
from enum import Enum
import uuid
import json


class MessageType(str, Enum):
    """消息类型"""
    REQUEST = "request"     # 请求
    RESPONSE = "response"   # 响应
    ERROR = "error"        # 错误
    EVENT = "event"        # 事件


class AgentMessage(BaseModel):
    """Agent 之间的标准化消息格式"""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "from_agent": "resume_analyzer",
                "to_agent": "coordinator",
                "message_type": "response",
                "payload": {"status": "success", "profile": {...}}
            }
        }
    )

    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="消息 ID")
    from_agent: str = Field(..., description="发送者 Agent 名称")
    to_agent: str = Field(..., description="接收者 Agent 名称")
    message_type: MessageType = Field(..., description="消息类型")
    payload: Dict[str, Any] = Field(default_factory=dict, description="实际数据")
    correlation_id: Optional[str] = Field(None, description="关联 ID")
    timestamp: datetime = Field(default_factory=datetime.now, description="时间戳")
    requires_response: bool = Field(default=False, description="是否需要回复")

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return self.model_dump()

    def to_json(self) -> str:
        """转换为 JSON"""
        return self.model_dump_json()

    @classmethod
    def from_json(cls, json_str: str) -> "AgentMessage":
        """从 JSON 创建"""
        data = json.loads(json_str)
        return cls(**data)

    def create_response(self, payload: Dict[str, Any]) -> "AgentMessage":
        """创建响应消息"""
        return AgentMessage(
            from_agent=self.to_agent,
            to_agent=self.from_agent,
            message_type=MessageType.RESPONSE,
            payload=payload,
            correlation_id=self.message_id
        )

    def create_error(self, error: str) -> "AgentMessage":
        """创建错误消息"""
        return AgentMessage(
            from_agent=self.to_agent,
            to_agent=self.from_agent,
            message_type=MessageType.ERROR,
            payload={"error": error},
            correlation_id=self.message_id
        )