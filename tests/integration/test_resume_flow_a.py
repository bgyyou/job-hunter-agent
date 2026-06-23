# -*- coding: utf-8 -*-
"""P2-3 Flow A 端到端测试：行业选择 → 对话 → 提取 → RAG 骨架 → 生成简历

mock LLM 返回，验证状态流转和数据传递。RAG 检索失败做兜底。
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.resume_flow_a import ResumeFlowA
from tools.llm import LLMResponse
from tools import taxonomy


# ---------- 工具函数：mock LLM ----------

def _llm_with_responses(*texts):
    """LLM 按顺序返回 N 条文本"""
    client = AsyncMock()
    responses = [LLMResponse(content=t, model="mock", tokens_used=10, finish_reason="stop") for t in texts]
    client.analyze = AsyncMock(side_effect=responses)
    return client


# ---------- taxonomy 单元 ----------

def test_taxonomy_industries():
    industries = taxonomy.list_industries()
    assert isinstance(industries, list)
    assert len(industries) >= 5
    # 几个核心行业必须在
    assert any("互联网" in i for i in industries)


def test_taxonomy_functions_under_industry():
    industries = taxonomy.list_industries()
    for ind in industries[:3]:
        funcs = taxonomy.list_functions(ind)
        assert isinstance(funcs, list)


def test_taxonomy_positions_drill_down():
    funcs = taxonomy.list_functions("互联网/软件")
    assert "产品" in funcs
    positions = taxonomy.list_positions("互联网/软件", "产品")
    assert "AI产品经理" in positions


def test_taxonomy_positions_all_under_industry():
    """不指定职能时返回该行业所有岗位（去重）"""
    positions = taxonomy.list_positions("互联网/软件")
    assert len(positions) > 10
    # 来自不同职能的都要在
    assert "AI产品经理" in positions  # 产品
    assert "前端开发工程师" in positions  # 研发


# ---------- chat：继续提问 ----------

def test_chat_returns_question():
    flow = ResumeFlowA(_llm_with_responses("你好！请问你叫什么名字？你之前在哪些公司工作过？"))
    loop = asyncio.new_event_loop()
    try:
        reply = loop.run_until_complete(flow.chat(
            messages=[{"role": "user", "content": "我想申请 AI 产品经理"}],
            industry="互联网/软件",
            position="AI产品经理",
        ))
    finally:
        loop.close()
    assert reply["type"] == "question"
    assert "名字" in reply["message"]


# ---------- chat：DONE 标记 ----------

def test_chat_detects_done_marker():
    flow = ResumeFlowA(_llm_with_responses("好的，信息已收集完毕，我为你生成简历。[DONE]"))
    loop = asyncio.new_event_loop()
    try:
        reply = loop.run_until_complete(flow.chat(
            messages=[{"role": "user", "content": "没了"}],
            industry="互联网/软件",
            position="AI产品经理",
        ))
    finally:
        loop.close()
    assert reply["type"] == "done"
    assert "[DONE]" not in reply["message"]


def test_chat_force_done_when_max_rounds_reached():
    """达到 max_rounds 上限时，即使 LLM 不输出 [DONE]，也强制收尾。"""
    flow = ResumeFlowA(_llm_with_responses("感谢你的回答，那我们再聊聊..."))
    # 构造 8 轮 assistant 消息 → 达到 max_rounds=8 上限
    history = []
    for i in range(8):
        history.append({"role": "user", "content": f"user msg {i}"})
        history.append({"role": "assistant", "content": f"asst msg {i}"})
    history.append({"role": "user", "content": "继续"})

    loop = asyncio.new_event_loop()
    try:
        reply = loop.run_until_complete(flow.chat(
            messages=history, industry="互联网/软件",
            position="AI产品经理", max_rounds=8,
        ))
    finally:
        loop.close()
    assert reply["type"] == "done"
    assert reply["rounds_used"] == 8


# ---------- extract_resume ----------

def test_extract_resume_parses_json():
    extracted_json = json.dumps({
        "header": {"name": "Leon", "contact": {"phone": "123", "email": "l@e.com"}, "summary": "5 年产品经验"},
        "experience": [{"title": "PM", "company": "ACME", "duration": "2020-2023", "achievements": ["launched X"]}],
        "skills": ["Python", "SQL"],
        "education": [{"school": "CUHK", "degree": "硕士", "major": "IS"}],
        "projects": [],
    }, ensure_ascii=False)
    flow = ResumeFlowA(_llm_with_responses(extracted_json))
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(flow.extract_resume([
            {"role": "user", "content": "我叫 Leon"},
            {"role": "assistant", "content": "你好 Leon"},
        ]))
    finally:
        loop.close()
    assert result["header"]["name"] == "Leon"
    assert result["skills"] == ["Python", "SQL"]


# ---------- build_skeleton: RAG 失败兜底 ----------

def test_build_skeleton_empty_when_no_rag_results(monkeypatch):
    """RAG 没有数据时，build_skeleton 应返回 source='fallback' 的兜底骨架。"""
    flow = ResumeFlowA(_llm_with_responses(""))

    # mock Retriever 返回空
    from tools import retriever as retriever_mod
    monkeypatch.setattr(retriever_mod, "Retriever", lambda: MagicMock(retrieve=MagicMock(return_value=[])))

    loop = asyncio.new_event_loop()
    try:
        skeleton = loop.run_until_complete(flow.build_skeleton("AI产品经理", "互联网/软件"))
    finally:
        loop.close()
    assert isinstance(skeleton, dict)
    assert skeleton["source"] == "fallback"
    assert skeleton["n_chunks"] == 0
    assert "AI产品经理" in skeleton["text"]  # 兜底文案含目标 position


def test_build_skeleton_with_rag_data(monkeypatch):
    """RAG 命中时，会调用 LLM 提炼并返回 source='rag' 的骨架。"""
    flow = ResumeFlowA(_llm_with_responses("1. 熟悉 LLM 应用\n2. 有产品 0-1 经验\n3. 数据驱动决策"))

    # mock Retriever 返回 requirement chunk
    mock_chunks = [
        {"chunk_text": "熟悉大语言模型应用开发", "chunk_type": "requirement",
         "metadata": {"jd_industry_tag": "互联网/软件"}},
        {"chunk_text": "具有 0-1 产品经验", "chunk_type": "requirement",
         "metadata": {"jd_industry_tag": "快消"}},
    ]
    from tools import retriever as retriever_mod
    monkeypatch.setattr(retriever_mod, "Retriever", lambda: MagicMock(retrieve=MagicMock(return_value=mock_chunks)))

    loop = asyncio.new_event_loop()
    try:
        skeleton = loop.run_until_complete(flow.build_skeleton("AI产品经理", "互联网/软件"))
    finally:
        loop.close()
    assert skeleton["source"] == "rag"
    assert skeleton["n_chunks"] == 2
    assert set(skeleton["industries_covered"]) == {"互联网/软件", "快消"}
    assert "LLM" in skeleton["text"] or "产品" in skeleton["text"]


# ---------- generate_final：组合 extracted + skeleton ----------

def test_generate_final_produces_resume_dict():
    extracted = {
        "header": {"name": "Leon", "contact": {"phone": "123", "email": "l@e.com"}},
        "experience": [],
        "skills": ["Python"],
        "education": [],
        "projects": [],
    }

    final_json = json.dumps({
        "header": {"name": "Leon", "contact": {"phone": "123", "email": "l@e.com"}, "summary": "AI 产品经理候选人"},
        "experience": [],
        "skills": ["Python", "LLM", "RAG"],
        "education": [],
        "projects": [],
    }, ensure_ascii=False)

    flow = ResumeFlowA(_llm_with_responses(final_json))
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(flow.generate_final(
            extracted,
            skeleton={"text": "1. 熟悉 LLM 应用", "source": "rag",
                      "n_chunks": 1, "industries_covered": ["互联网/软件"]},
            position="AI产品经理",
        ))
    finally:
        loop.close()
    assert "LLM" in result["skills"]


def test_generate_final_falls_back_on_bad_json():
    """LLM 返回非 JSON 时，应回退到 extracted 数据"""
    extracted = {"header": {"name": "Leon"}, "skills": ["X"]}
    flow = ResumeFlowA(_llm_with_responses("抱歉无法生成"))
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(flow.generate_final(
            extracted,
            skeleton={"text": "", "source": "fallback", "n_chunks": 0, "industries_covered": []},
            position="AI产品经理",
        ))
    finally:
        loop.close()
    assert result == extracted


# ---------- 端到端：完整 Flow A 链路 ----------

def test_flow_a_end_to_end(monkeypatch):
    """对话 → 提取 → RAG → 生成 → markdown 全链路"""
    # 第 1 次 LLM 调用: chat 回应 "完毕[DONE]"
    # 第 2 次: extract 返回结构化 JSON
    # 第 3 次: build_skeleton 内部提炼要求
    # 第 4 次: generate_final 返回最终 JSON
    extracted_json = json.dumps({
        "header": {"name": "Leon", "contact": {"phone": "123", "email": "l@e.com"}, "summary": "产品经理"},
        "experience": [{"title": "PM", "company": "ACME", "duration": "2020-2023", "achievements": ["launched X"]}],
        "skills": ["Python"],
        "education": [{"school": "CUHK", "degree": "硕士", "major": "IS"}],
        "projects": [],
    }, ensure_ascii=False)
    skeleton_text = "1. LLM 应用\n2. 数据驱动"
    final_json = json.dumps({
        "header": {"name": "Leon", "contact": {"phone": "123", "email": "l@e.com"}, "summary": "AI PM 候选人"},
        "experience": [{"title": "AI PM", "company": "ACME", "duration": "2020-2023", "achievements": ["主导 X 0-1"]}],
        "skills": ["Python", "LLM", "RAG"],
        "education": [{"school": "CUHK", "degree": "硕士", "major": "IS"}],
        "projects": [],
    }, ensure_ascii=False)

    flow = ResumeFlowA(_llm_with_responses(extracted_json, skeleton_text, final_json))

    mock_chunks = [{"chunk_text": "熟悉 LLM", "chunk_type": "requirement"}]
    from tools import retriever as retriever_mod
    monkeypatch.setattr(retriever_mod, "Retriever", lambda: MagicMock(retrieve=MagicMock(return_value=mock_chunks)))

    messages = [
        {"role": "user", "content": "我想申请 AI 产品经理"},
        {"role": "assistant", "content": "你叫什么名字？"},
        {"role": "user", "content": "Leon"},
        {"role": "assistant", "content": "[DONE]"},
    ]

    loop = asyncio.new_event_loop()
    try:
        extracted = loop.run_until_complete(flow.extract_resume(messages))
        skeleton = loop.run_until_complete(flow.build_skeleton("AI产品经理", "互联网/软件"))
        final_data = loop.run_until_complete(flow.generate_final(extracted, skeleton, "AI产品经理"))
    finally:
        loop.close()

    md = flow.to_markdown(final_data)
    assert "# Leon" in md
    assert "LLM" in md
    assert "AI PM" in md
