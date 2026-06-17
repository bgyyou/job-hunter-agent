# models/job.py
from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import List, Optional
from datetime import datetime
from models.base import BaseEntity


class JobPosting(BaseEntity):
    """职位信息"""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "platform": "boss",
                "job_id": "12345",
                "title": "Python后端工程师",
                "company": "腾讯",
                "location": "深圳",
                "salary_min": 20,
                "salary_max": 35,
                "requirements": "要求熟悉Python、Django...",
                "skills_required": ["Python", "Django", "PostgreSQL"]
            }
        }
    )

    # 平台信息
    platform: str = Field(..., description="招聘平台：boss/liepin/jobsdb")
    job_id: str = Field(..., description="职位 ID")
    url: str = Field(..., description="职位链接")

    # 职位信息
    title: str = Field(..., description="职位名称")
    company: str = Field(..., description="公司名称")
    location: str = Field(..., description="工作地点")

    # 薪资
    salary_min: Optional[int] = Field(None, description="最低薪资")
    salary_max: Optional[int] = Field(None, description="最高薪资")

    # JD
    requirements: str = Field(..., description="职位描述/要求")
    skills_required: List[str] = Field(default_factory=list, description="要求的技能")

    # 时间
    posted_date: datetime = Field(default_factory=datetime.now, description="发布时间")
    scraped_at: datetime = Field(default_factory=datetime.now, description="爬取时间")

    @field_validator("salary_max")
    @classmethod
    def validate_salary_max(cls, v, info):
        """验证最高薪资"""
        if v is not None and info.data.get("salary_min") is not None:
            salary_min = info.data["salary_min"]
            if v < salary_min:
                raise ValueError("最低薪资不能高于最高薪资")
        return v

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, v):
        """验证平台名称"""
        valid_platforms = ["boss", "liepin", "jobsdb"]
        if v not in valid_platforms:
            raise ValueError(f"平台必须是: {', '.join(valid_platforms)}")
        return v

    @property
    def salary_range(self) -> str:
        """薪资范围字符串"""
        if self.salary_min is None or self.salary_max is None:
            return "面议"
        return f"{self.salary_min}k - {self.salary_max}k"