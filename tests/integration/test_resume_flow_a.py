# -*- coding: utf-8 -*-
"""Flow A 测试：section 状态机分段采集 → 派生 → RAG 骨架 → 渲染。

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


# ---------- build_skeleton: RAG 失败兜底 ----------

def test_build_skeleton_empty_when_no_rag_results(monkeypatch):
    """RAG 没有数据时，build_skeleton 应返回 source='fallback' 的兜底骨架。"""
    flow = ResumeFlowA(_llm_with_responses(""))

    # mock Retriever 返回空
    from tools import retriever as retriever_mod
    monkeypatch.setattr(retriever_mod, "Retriever", lambda **kw: MagicMock(retrieve=MagicMock(return_value=[])))

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
    monkeypatch.setattr(retriever_mod, "Retriever", lambda **kw: MagicMock(retrieve=MagicMock(return_value=mock_chunks)))

    loop = asyncio.new_event_loop()
    try:
        skeleton = loop.run_until_complete(flow.build_skeleton("AI产品经理", "互联网/软件"))
    finally:
        loop.close()
    assert skeleton["source"] == "rag"
    assert skeleton["n_chunks"] == 2
    assert set(skeleton["industries_covered"]) == {"互联网/软件", "快消"}
    assert "LLM" in skeleton["text"] or "产品" in skeleton["text"]


# ---------- _normalize_resume_shape：占位符剥除 ----------

def test_normalize_strips_llm_placeholders():
    """LLM 偷塞 [您的姓名] [X]年 202X.XX 这种占位符时，normalize 必须把它们剥成空。"""
    raw = {
        "header": {
            "name": "[您的姓名]",
            "contact": {"phone": "[您的手机号]", "email": "[您的邮箱]"},
            "summary": "拥有[X]年AI产品经验的产品经理。",
        },
        "experience": [
            {"title": "高级产品经理", "company": "[前一家公司名称]",
             "duration": "202X.XX - 至今",
             "achievements": ["上线 Agent 系统，满意度提升 30%"]},
        ],
        "skills": ["LLM", "xxx", "[待补充]"],
        "education": [{"school": "[大学名称]", "degree": "[学士/硕士]",
                       "major": "计算机", "start_year": "", "end_year": ""}],
        "projects": [],
    }
    result = ResumeFlowA._normalize_resume_shape(raw)
    # 占位符全被剥成空
    assert result["header"]["name"] == ""
    assert result["header"]["contact"]["phone"] == ""
    assert result["header"]["contact"]["email"] == ""
    assert "[X]" not in result["header"]["summary"]
    assert result["experience"][0]["company"] == ""
    # 202X.XX 被剥掉，可能残留"至今"，但不再有 X/占位符特征
    assert "X" not in result["experience"][0]["duration"]
    assert "[" not in result["experience"][0]["duration"]
    # 真实成果保留
    assert "30%" in result["experience"][0]["achievements"][0]
    # skills 里 xxx 和 [待补充] 被剥除，只剩 LLM
    assert result["skills"] == ["LLM"]
    assert result["education"][0]["school"] == ""
    assert result["education"][0]["major"] == "计算机"


# ---------- Section 状态机：新接线测试 ----------

def test_chat_section_collects_personal_info():
    """chat_section: 个人信息段，LLM 回答带 [SECTION_DONE] 时应识别为段完成。"""
    flow = ResumeFlowA(_llm_with_responses("好的，信息已记录。[SECTION_DONE]"))
    loop = asyncio.new_event_loop()
    try:
        reply = loop.run_until_complete(flow.chat_section(
            section_key="header",
            messages=[
                {"role": "assistant", "content": "请问你的姓名和联系方式？"},
                {"role": "user", "content": "我叫 Leon,电话 13800138000"},
            ],
            collected_so_far={},
            industry="互联网/软件",
            position="AI产品经理",
        ))
    finally:
        loop.close()
    assert reply["type"] == "section_done"
    assert "[SECTION_DONE]" not in reply["message"]


def test_chat_section_skip_marker():
    """chat_section: 用户跳过整段时识别 [SECTION_DONE,SKIP]。"""
    flow = ResumeFlowA(_llm_with_responses("好的，跳过本段。[SECTION_DONE,SKIP]"))
    loop = asyncio.new_event_loop()
    try:
        reply = loop.run_until_complete(flow.chat_section(
            section_key="experience",
            messages=[{"role": "user", "content": "我是应届毕业生没有工作经历"}],
            collected_so_far={},
            industry="互联网/软件",
            position="AI产品经理",
        ))
    finally:
        loop.close()
    assert reply["type"] == "section_skipped"


def test_extract_section_education():
    """extract_section: 教育经历段只提取该段 JSON。"""
    education_json = json.dumps([
        {"school": "CUHK", "degree": "硕士", "major": "信息系统", "start_year": "2018", "end_year": "2020"}
    ], ensure_ascii=False)
    flow = ResumeFlowA(_llm_with_responses(education_json))
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(flow.extract_section(
            section_key="education",
            messages=[
                {"role": "assistant", "content": "你的教育背景？"},
                {"role": "user", "content": "我硕士毕业于 CUHK，专业是信息系统，2018-2020"},
            ],
        ))
    finally:
        loop.close()
    assert isinstance(result, list)
    assert result[0]["school"] == "CUHK"


def test_derive_summary_and_competencies():
    """derive: 拿到 collected 数据后，LLM 派生 summary 和 core_competencies。"""
    derived_json = json.dumps({
        "summary": "AI 产品经理候选人，熟悉 LLM 应用落地。",
        "core_competencies": ["LLM 应用设计", "数据驱动决策", "产品 0-1 落地"],
    }, ensure_ascii=False)
    flow = ResumeFlowA(_llm_with_responses(derived_json))
    collected = {
        "header": {"name": "Leon"},
        "experience": [{"title": "PM", "company": "ACME"}],
        "skills": ["Python", "LLM"],
    }
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(flow.derive_summary_and_competencies(
            collected, industry="互联网/软件", position="AI产品经理",
        ))
    finally:
        loop.close()
    assert "AI 产品" in result["summary"]
    assert len(result["core_competencies"]) == 3


def test_section_data_roundtrip_to_markdown():
    """8 个 section 的 collected dict → normalize → to_markdown，验证新字段都被渲染。"""
    flow = ResumeFlowA(_llm_with_responses(""))
    full_data = {
        "header": {
            "name": "Leon",
            "contact": {"phone": "13800138000", "email": "leon@example.com",
                        "wechat": "leon_wx", "linkedin": "linkedin.com/in/leon"},
        },
        "summary": "AI PM 候选人",
        "core_competencies": ["LLM 应用", "产品 0-1", "数据驱动"],
        "experience": [{"title": "PM", "company": "ACME", "duration": "2020-2023",
                        "achievements": ["DAU 提升 30%"]}],
        "projects": [{"name": "Chatbot", "role": "PM", "description": "聊天机器人",
                      "tech_stack": ["Python", "LLM"]}],
        "skills": ["Python", "LLM", "SQL"],
        "education": [{"school": "CUHK", "degree": "硕士", "major": "IS",
                       "start_year": "2018", "end_year": "2020"}],
        "languages": [{"name": "中文", "level": "母语"}, {"name": "英文", "level": "流利"}],
    }
    normalized = flow._normalize_resume_shape(full_data)
    # 新字段都进了 normalized
    assert normalized["summary"] == "AI PM 候选人"
    assert normalized["core_competencies"] == ["LLM 应用", "产品 0-1", "数据驱动"]
    assert normalized["languages"][0]["name"] == "中文"
    assert normalized["header"]["contact"]["wechat"] == "leon_wx"

    # markdown 渲染包含 8 个段
    md = flow.to_markdown(normalized)
    assert "# Leon" in md
    assert "## 个人陈述" in md
    assert "## 核心能力" in md
    assert "LLM 应用" in md
    assert "## 工作经历" in md
    assert "## 项目经历" in md
    assert "## 技能" in md
    assert "## 教育背景" in md
    assert "## 语言能力" in md
    assert "中文" in md and "母语" in md
