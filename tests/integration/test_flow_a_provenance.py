# -*- coding: utf-8 -*-
"""PR3: Flow A 收尾 JD 来源面板 — 测试 build_skeleton 返回 source_breakdown 的纯函数部分。

不 streamlit 渲染，只测 _build_source_breakdown 聚合逻辑。"""
from __future__ import annotations

import pytest

from agents.resume_flow_a import ResumeFlowA


def _chunk(jd_id, platform="51job", sim=0.7, text="chunk text"):
    return {
        "chunk_id": f"c_{jd_id}",
        "jd_id": jd_id,
        "chunk_text": text,
        "chunk_type": "requirement",
        "similarity": sim,
        "metadata": {
            "jd_platform": platform,
            "jd_industry_tag": "互联网",
            "jd_function_tag": "产品",
            "jd_position_tag": "AI产品经理",
        },
    }


def test_build_source_breakdown_counts_platforms():
    chunks = [
        _chunk("jd1", "51job"),
        _chunk("jd2", "51job"),
        _chunk("jd3", "jobsdb"),
        _chunk("jd4", "liepin"),
    ]
    result = ResumeFlowA._build_source_breakdown(chunks)
    assert result["platform_counts"] == {"51job": 2, "jobsdb": 1, "liepin": 1}
    assert result["n_companies"] == 4
    assert len(result["top_jd_ids"]) == 4
    assert len(result["top_chunks"]) == 4


def test_build_source_breakdown_dedup_repeated_jd():
    """同一 JD 多个 chunk 只算一家公司。"""
    chunks = [
        _chunk("jd1"),
        _chunk("jd1"),
        _chunk("jd2"),
    ]
    result = ResumeFlowA._build_source_breakdown(chunks)
    assert result["n_companies"] == 2
    assert set(result["top_jd_ids"]) == {"jd1", "jd2"}


def test_build_source_breakdown_handles_empty_list():
    result = ResumeFlowA._build_source_breakdown([])
    assert result["platform_counts"] == {}
    assert result["n_companies"] == 0
    assert result["top_jd_ids"] == []
    assert result["top_chunks"] == []


def test_build_source_breakdown_handles_chunks_without_platform():
    chunks = [_chunk("jd1", platform=None)]
    result = ResumeFlowA._build_source_breakdown(chunks)
    # 缺失 platform 兜底为 "other"
    assert result["platform_counts"] == {"other": 1}


def test_build_source_breakdown_top_5_cap():
    """top_chunks 限前 5。"""
    chunks = [_chunk(f"jd{i}") for i in range(10)]
    result = ResumeFlowA._build_source_breakdown(chunks)
    assert len(result["top_chunks"]) == 5
