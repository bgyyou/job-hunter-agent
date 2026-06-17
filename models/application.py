# models/application.py
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime
from models.base import BaseEntity
from enum import Enum


class ApplicationStatus(str, Enum):
    """投递状态"""
    PENDING = "pending"      # 待投递
    SUBMITTED = "submitted"  # 已投递
    FAILED = "failed"        # 失败


class ApplicationMethod(str, Enum):
    """投递方式"""
    AUTO = "auto"     # 自动
    MANUAL = "manual" # 手动


class ApplicationRecord(BaseEntity):
    """投递记录"""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "job_id": "12345",
                "resume_version": "v1.0",
                "status": "submitted",
                "method": "auto"
            }
        }
    )

    job_id: str = Field(..., description="职位 ID")
    resume_version: str = Field(..., description="使用的简历版本")
    applied_at: datetime = Field(default_factory=datetime.now, description="投递时间")
    status: ApplicationStatus = Field(default=ApplicationStatus.PENDING, description="投递状态")
    method: ApplicationMethod = Field(..., description="投递方式")
    error: Optional[str] = Field(None, description="错误信息")

    @property
    def is_successful(self) -> bool:
        """是否成功"""
        return self.status == ApplicationStatus.SUBMITTED

    @property
    def is_failed(self) -> bool:
        """是否失败"""
        return self.status == ApplicationStatus.FAILED