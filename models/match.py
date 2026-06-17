# models/match.py
from pydantic import BaseModel, Field, field_validator, ConfigDict, model_validator
from typing import List, Dict
from models.base import BaseEntity


class Gap(BaseModel):
    """差距项"""
    model_config = ConfigDict(extra="allow")

    type: str = Field(..., description="差距类型：missing_skill/experience_short/etc")
    description: str = Field(..., description="描述")
    importance: str = Field(..., description="重要性：high/medium/low")


class MatchResult(BaseEntity):
    """匹配结果"""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "job_id": "12345",
                "score": 85,
                "reasoning": "技能匹配度高，经验符合要求",
                "gaps": [
                    {
                        "type": "missing_skill",
                        "description": "缺少 Kubernetes 经验",
                        "importance": "high"
                    }
                ],
                "recommendations": ["建议学习 Kubernetes", "突出相关项目经验"],
                "should_apply": True
            }
        }
    )

    job_id: str = Field(..., description="职位 ID")
    score: float = Field(..., ge=0, le=100, description="匹配度分数 (0-100)")
    reasoning: str = Field(..., description="匹配理由")
    gaps: List[Gap] = Field(default_factory=list, description="差距分析")
    recommendations: List[str] = Field(default_factory=list, description="建议")
    should_apply: bool = Field(default=False, description="是否建议投递")

    @model_validator(mode="after")
    def auto_set_should_apply(self):
        """根据分数自动设置是否应该投递"""
        self.should_apply = self.score >= 70
        return self

    @property
    def match_level(self) -> str:
        """匹配等级"""
        if self.score >= 85:
            return "高"
        elif self.score >= 70:
            return "中"
        else:
            return "低"

    def get_high_importance_gaps(self) -> List[Gap]:
        """获取高重要性的差距"""
        return [gap for gap in self.gaps if gap.importance == "high"]