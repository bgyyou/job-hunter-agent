# -*- coding: utf-8 -*-
"""v2.1 M4.3: SemanticChunker 单测。

覆盖：
- 中文 4 类 chunk_type 全部命中
- 英文章节标题命中
- bullet 前缀剥除
- 长文本按句号切分
- 完全无结构文本兜底为 overview
- 空输入返回 []
"""
from __future__ import annotations

import pytest

from tools.chunker import SemanticChunker, CHUNK_TYPES


def test_empty_input():
    assert SemanticChunker().split("") == []
    assert SemanticChunker().split("   \n  \n  ") == []


def test_chinese_full_coverage():
    text = """职位描述：
我们正在招募一名 AI 产品经理参与 LLM 应用建设。

岗位职责：
- 负责 AI 产品的规划与落地
- 推动跨团队协作完成 PRD

任职要求：
- 3 年以上互联网产品经验
- 熟悉 LLM、RAG、Agent 应用架构

加分项：
- 有 ToB SaaS 产品交付经验
- 具备技术研发背景
"""
    chunks = SemanticChunker().split(text)
    types = {c.chunk_type for c in chunks}
    assert "responsibility" in types
    assert "requirement" in types
    assert "nice_to_have" in types
    # overview 章节里有内容，也应进 chunk
    assert "overview" in types
    # 全部类型都属于合法集合
    assert types.issubset(set(CHUNK_TYPES))


def test_english_headings():
    text = """About the Role:
We are hiring a Senior PM.

Responsibilities:
- Define product roadmap
- Work with engineering

Requirements:
- 5+ years in PM
- Strong analytics skills

Nice to have:
- ML background
"""
    chunks = SemanticChunker().split(text)
    types = {c.chunk_type for c in chunks}
    assert {"responsibility", "requirement", "nice_to_have"}.issubset(types)


def test_bullet_prefix_stripped():
    text = """岗位职责：
• 负责 AI 产品的规划与设计
- 推动跨团队协作完成需求落地
1. 跟进 LLM 与 RAG 技术选型
"""
    chunks = SemanticChunker().split(text)
    resp = [c for c in chunks if c.chunk_type == "responsibility"]
    assert len(resp) == 3
    # bullet 前缀已被剥掉
    for c in resp:
        assert not c.chunk_text.startswith("•")
        assert not c.chunk_text.startswith("-")
        assert not c.chunk_text.startswith("1.")


def test_heading_path_recorded():
    text = """岗位职责：
- 负责 AI 产品规划
"""
    chunks = SemanticChunker().split(text)
    resp = [c for c in chunks if c.chunk_type == "responsibility"]
    assert resp
    assert resp[0].heading_path  # heading 被保留
    assert "岗位职责" in resp[0].heading_path[0]


def test_unstructured_fallback_overview():
    text = "这是一段没有任何标题的 JD 描述，全文应作为单条 overview 入 chunk。"
    chunks = SemanticChunker().split(text)
    assert len(chunks) == 1
    assert chunks[0].chunk_type == "overview"
    assert chunks[0].chunk_text == text


def test_min_length_filter():
    """过短的内容应被丢弃。"""
    text = """岗位职责：
a
- 这是一条足够长的真实职责描述
"""
    chunks = SemanticChunker().split(text)
    resp = [c for c in chunks if c.chunk_type == "responsibility"]
    # "a" 太短被过滤；只剩长 bullet
    assert len(resp) == 1
    assert "真实职责描述" in resp[0].chunk_text


def test_max_length_capping():
    """超长段落按句号 + 空白切多段。"""
    # 句号后加空格才能触发 _cap_length 的 split
    long_text = "这是一句相当冗长的描述内容。 " * 60  # ~1500 字
    text = "岗位职责：\n" + long_text
    chunks = SemanticChunker().split(text)
    # 至少切成多段
    assert len(chunks) >= 2
    assert all(len(c.chunk_text) <= SemanticChunker.MAX_CHUNK_LEN for c in chunks)


def test_chunks_to_dict_serializable():
    text = "岗位职责：\n- 负责产品规划"
    chunks = SemanticChunker().split(text)
    for c in chunks:
        d = c.to_dict()
        assert "chunk_text" in d
        assert "chunk_type" in d
        assert "heading_path" in d
