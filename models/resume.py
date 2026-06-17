# models/resume.py
from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import List, Dict
from models.base import BaseEntity


class Education(BaseModel):
    """教育背景"""
    model_config = ConfigDict(extra="allow")

    school: str = Field(..., description="学校")
    degree: str = Field(..., description="学位")
    major: str = Field(..., description="专业")
    start_year: int = Field(..., description="开始年份")
    end_year: int = Field(..., description="结束年份")


class Project(BaseModel):
    """项目经验"""
    model_config = ConfigDict(extra="allow")

    name: str = Field(..., description="项目名称")
    description: str = Field(..., description="项目描述")
    role: str = Field(..., description="角色")
    tech_stack: List[str] = Field(default_factory=list, description="技术栈")
    start_date: str = Field(..., description="开始日期")
    end_date: str = Field(..., description="结束日期")


class ResumeProfile(BaseEntity):
    """简历画像"""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "张三",
                "phone": "13800138000",
                "email": "zhangsan@example.com",
                "skills": ["Python", "Django", "PostgreSQL"],
                "experience_years": 3,
                "target_roles": ["后端工程师", "全栈工程师"],
                "preferred_locations": ["深圳", "广州"],
                "domains": ["Web开发", "数据处理"]
            }
        }
    )

    # 基本信息
    name: str = Field(..., description="姓名")
    phone: str = Field(..., description="电话号码")
    email: str = Field(..., description="邮箱")

    # 技能和经验
    skills: List[str] = Field(default_factory=list, description="技能列表")
    experience_years: int = Field(default=0, ge=0, description="工作年限")
    domains: List[str] = Field(default_factory=list, description="技术领域")

    # 目标和偏好
    target_roles: List[str] = Field(default_factory=list, description="目标岗位")
    preferred_locations: List[str] = Field(default_factory=list, description="偏好城市")

    # 详细信息
    education: List[Education] = Field(default_factory=list, description="教育背景")
    projects: List[Project] = Field(default_factory=list, description="项目经验")

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        """验证邮箱格式"""
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError("邮箱格式不正确")
        return v

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v):
        """验证电话格式"""
        v = v.replace(" ", "").replace("-", "")
        if not v.isdigit() or len(v) < 11:
            raise ValueError("电话号码格式不正确")
        return v