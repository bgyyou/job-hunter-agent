# -*- coding: utf-8 -*-
"""PR5: ResumeFlowA.extract_from_paste — 一次性结构化抽取。

调 mock LLM，不依赖真实网络。"""
from __future__ import annotations

import json
import pytest

from agents.resume_flow_a import ResumeFlowA


class _FakeLLMMessage:
    def __init__(self, role, content):
        self.role = role
        self.content = content


class _FakeLLMResponse:
    def __init__(self, content):
        self.content = content


def _make_flow_a(reply_json):
    """Create a ResumeFlowA with stub llm_client that returns reply_json."""
    class _FakeLLM:
        async def analyze(self, messages, max_tokens=1000, temperature=0.2):
            return _FakeLLMResponse(json.dumps(reply_json, ensure_ascii=False))

    return ResumeFlowA(_FakeLLM())


@pytest.mark.asyncio
async def test_extract_from_paste_experience_success():
    flow = _make_flow_a([
        {"title": "AI PM", "company": "ACME", "duration": "2022-2024",
         "achievements": ["带 5 人团队", "产品 DAU 翻倍"]},
    ])
    result = await flow.extract_from_paste(
        "experience", "2022-2024 ACME AI 产品经理...（中文长文本）"
    )
    assert isinstance(result, list)
    assert result[0]["company"] == "ACME"
    assert result[0]["achievements"] == ["带 5 人团队", "产品 DAU 翻倍"]


@pytest.mark.asyncio
async def test_extract_from_paste_projects_success():
    flow = _make_flow_a([
        {"name": "智能客服", "role": "PM", "tech_stack": ["LLM", "RAG"],
         "description": "从 0 到 1 搭建", "achievements": ["覆盖 10+ 业务线"]},
    ])
    result = await flow.extract_from_paste("projects", "智能客服 / PM / 技术栈：LLM, RAG")
    assert len(result) == 1
    assert result[0]["name"] == "智能客服"


@pytest.mark.asyncio
async def test_extract_from_paste_empty_text_returns_empty():
    """空文本 → 直接返空结构，不调 LLM。"""
    call_count = {"n": 0}

    class _CountLLM:
        async def analyze(self, messages, **kw):
            call_count["n"] += 1
            return _FakeLLMResponse("[]")

    flow = ResumeFlowA(_CountLLM())
    result = await flow.extract_from_paste("experience", "")
    assert result == []
    assert call_count["n"] == 0


@pytest.mark.asyncio
async def test_extract_from_paste_handles_bad_json_gracefully():
    """LLM 返回非 JSON 时回退空结构，不抛。"""

    class _BadLLM:
        async def analyze(self, messages, **kw):
            return _FakeLLMResponse("不是 JSON，是文字")

    flow = ResumeFlowA(_BadLLM())
    result = await flow.extract_from_paste("experience", "some text")
    # _parse_json_loose 对纯文本找不到 { 或 [，返 None → 空结构
    assert result in ([], {})


@pytest.mark.asyncio
async def test_extract_from_paste_strips_placeholders():
    """LLM 偷塞占位符 [您的姓名] / 202X 应被剥掉。"""
    flow = _make_flow_a([
        {"title": "AI PM[您的姓名]", "company": "ACME", "duration": "202X",
         "achievements": ["xxx 完成 100 个 xxx"]},
    ])
    result = await flow.extract_from_paste("experience", "text")
    assert "[您的姓名]" not in result[0]["title"]
    assert "202X" not in result[0]["duration"]
    assert "xxx" not in (result[0]["achievements"][0] or "")
