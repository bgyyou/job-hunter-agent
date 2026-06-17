# models/base.py
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Any, Dict
import uuid


class BaseEntity(BaseModel):
    """所有实体的基类"""

    model_config = ConfigDict(json_schema_extra={"example": {"id": "uuid"}})

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaseEntity":
        """从字典创建实例"""
        return cls(**data)