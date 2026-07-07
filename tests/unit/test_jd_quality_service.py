# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from services.jd_quality_service import (
    compute_jd_quality,
    quality_label,
)


def _jd(**overrides):
    base = {
        "id": "jd-1",
        "user_id": "default",
        "url": "https://example.com/1",
        "title": "AI PM",
        "company": "ACME",
        "location": "深圳",
        "salary_str": "30-50K",
        "parsed_sections": {
            "requirements": ["LLM 经验", "RAG 经验", "产品规划"],
            "preferred": ["B 端背景"],
        },
        "tags": ["LLM", "RAG", "产品", "Python", "SQL"],
        "raw_text": "岗位：AI 产品经理\n职责：xxx\n要求：xxx\n" * 80,
        "source": "51job_batch",
        "platform": "51job",
        "industry_tag": "互联网",
        "function_tag": "产品",
        "position_tag": "AI产品经理",
        "crawled_at": "2026-07-01T00:00:00+00:00",
        "deleted_at": None,
    }
    base.update(overrides)
    return base


def test_quality_label_thresholds():
    assert quality_label(None) == "未评分"
    assert quality_label(0.95) == "★★★★"
    assert quality_label(0.70) == "★★★★"
    assert quality_label(0.69) == "★★★"
    assert quality_label(0.50) == "★★★"
    assert quality_label(0.49) == "★★"
    assert quality_label(0.30) == "★★"
    assert quality_label(0.29) == "★"
    assert quality_label(0.00) == "★"


def test_compute_full_rich_recent_jd_scores_high():
    now = datetime(2026, 7, 7, tzinfo=timezone.utc)
    jd = _jd(crawled_at=(now - timedelta(days=3)).isoformat())
    # 默认 _jd raw_text 已 = "岗位：AI 产品经理\n... " * 80 → 2400 字符 → richness=0.9
    result = compute_jd_quality(jd, now=now)
    assert result["parse_completeness"] >= 0.9
    assert result["source_authority"] == 0.90
    assert result["freshness"] >= 0.94  # 3 天 → sigmoid(2.9) ≈ 0.948
    assert result["text_richness"] == 0.9
    assert result["composite"] >= 0.85
    assert result["is_garbage"] is False


def test_compute_handles_missing_fields_gracefully():
    now = datetime(2026, 7, 7, tzinfo=timezone.utc)
    jd = {
        "id": "jd-thin",
        "source": "51job_batch",
        "raw_text": "hello",
        "crawled_at": None,
        "parsed_sections": {},
        "tags": [],
    }
    result = compute_jd_quality(jd, now=now)
    # 所有字段应有合理 fallback，不抛异常
    assert 0 <= result["parse_completeness"] <= 1
    assert result["freshness"] == 0.5  # 无 crawled_at 默认中等
    assert result["text_richness"] < 0.5  # 短文本
    assert result["composite"] < 0.7


def test_compute_garbage_jd_capped_low():
    now = datetime(2026, 7, 7, tzinfo=timezone.utc)
    jd = _jd(
        source="51job_batch",
        title="登录",
        company="",
        raw_text="需要验证 请输入验证码",
        parsed_sections={},
        tags=[],
        crawled_at=now.isoformat(),
    )
    result = compute_jd_quality(jd, now=now)
    assert result["is_garbage"] is True
    assert result["composite"] <= 0.20


def test_compute_non_crawled_source_bypasses_garbage_check():
    """manual / pdf / url 不在 CRAWLED_SOURCES，永远不标 garbage。"""
    now = datetime(2026, 7, 7, tzinfo=timezone.utc)
    jd = _jd(
        source="manual",
        title="登录",
        raw_text="xxx",
        crawled_at=now.isoformat(),
    )
    result = compute_jd_quality(jd, now=now)
    assert result["is_garbage"] is False


def test_compute_freshness_sigmoid():
    now = datetime(2026, 7, 7, tzinfo=timezone.utc)
    very_fresh = _jd(crawled_at=(now - timedelta(days=3)).isoformat())
    medium = _jd(crawled_at=(now - timedelta(days=90)).isoformat())
    stale = _jd(crawled_at=(now - timedelta(days=365)).isoformat())
    ancient = _jd(crawled_at=(now - timedelta(days=730)).isoformat())

    f_fresh = compute_jd_quality(very_fresh, now=now)["freshness"]
    f_med = compute_jd_quality(medium, now=now)["freshness"]
    f_stale = compute_jd_quality(stale, now=now)["freshness"]
    f_ancient = compute_jd_quality(ancient, now=now)["freshness"]

    assert f_fresh > f_med > f_stale > f_ancient
    assert f_ancient < 0.1


def test_compute_source_authority_table():
    """不同 source 拿到对应 authority 分数。"""
    now = datetime(2026, 7, 7, tzinfo=timezone.utc)
    assert compute_jd_quality(_jd(source="51job_batch"), now=now)["source_authority"] == 0.90
    assert compute_jd_quality(_jd(source="jobsdb_batch"), now=now)["source_authority"] == 0.90
    assert compute_jd_quality(_jd(source="liepin_batch"), now=now)["source_authority"] == 0.70
    assert compute_jd_quality(_jd(source="manual"), now=now)["source_authority"] == 0.85
    assert compute_jd_quality(_jd(source="pdf"), now=now)["source_authority"] == 0.85
    assert compute_jd_quality(_jd(source="unknown_xyz"), now=now)["source_authority"] == 0.70


def test_compute_soft_deleted_jd_zero_authority():
    now = datetime(2026, 7, 7, tzinfo=timezone.utc)
    jd = _jd(deleted_at="2026-07-01T00:00:00")
    assert compute_jd_quality(jd, now=now)["source_authority"] == 0.0
