# models/traceable_result.py
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Dict, Optional
from datetime import datetime
from models.base import BaseEntity


class Source(BaseModel):
    """来源引用"""
    model_config = ConfigDict(extra="allow")

    source_id: str = Field(..., description="来源 ID")
    text: str = Field(..., description="来源内容")
    relevance: str = Field(..., description="相关性说明")


class LLMCall(BaseModel):
    """LLM 调用记录"""
    model_config = ConfigDict(extra="allow")

    prompt: str = Field(..., description="Prompt")
    response: str = Field(..., description="响应")
    timestamp: datetime = Field(default_factory=datetime.now, description="时间")
    tokens_used: int = Field(default=0, description="使用的 Token 数")


class TraceableResult(BaseEntity):
    """可追溯的 AI 结果"""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "content": "匹配度 85%，建议投递",
                "reasoning": "技能匹配度高，经验符合要求",
                "confidence": 0.85,
                "agent_name": "matcher"
            }
        }
    )

    content: str = Field(..., description="核心内容")
    sources: List[Source] = Field(default_factory=list, description="来源列表")
    reasoning: str = Field(default="", description="决策理由")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="置信度 (0-1)")
    llm_calls: List[LLMCall] = Field(default_factory=list, description="LLM 调用记录")
    intermediate_results: List[Dict] = Field(default_factory=list, description="中间结果")
    timestamp: datetime = Field(default_factory=datetime.now, description="时间戳")
    agent_name: str = Field(..., description="Agent 名称")

    def add_source(self, source_id: str, source_text: str, relevance: str):
        """添加来源"""
        source = Source(
            source_id=source_id,
            text=source_text,
            relevance=relevance
        )
        self.sources.append(source)

    def add_llm_call(self, prompt: str, response: str, tokens_used: int = 0):
        """添加 LLM 调用记录"""
        call = LLMCall(
            prompt=prompt,
            response=response,
            tokens_used=tokens_used
        )
        self.llm_calls.append(call)

    def to_explainable(self) -> str:
        """生成可解释的输出"""
        output = f"""结果: {self.content}

置信度: {self.confidence:.1%}

决策理由:
{self.reasoning}

来源:"""
        for i, source in enumerate(self.sources, 1):
            text_preview = source.text[:100] + "..." if len(source.text) > 100 else source.text
            output += f"""
{i}. 来源 {source.source_id}
   内容: {text_preview}
   相关性: {source.relevance}"""
        return output.strip()

    @property
    def is_high_confidence(self) -> bool:
        """是否高置信度"""
        return self.confidence >= 0.8