# -*- coding: utf-8 -*-
"""PR2: jd 卡片元数据渲染 helpers + 懒评分。

与 jd_library_service 解耦测试，不直接 streamlit 渲染，验证纯函数输出。"""
from __future__ import annotations

import importlib

import pytest

import web_app  # noqa: E402
page_mod_1 = importlib.import_module('pages.07_📚_JD_Library')



def _row(**overrides):
    base = {
        "id": "jd-x",
        "source": "51job_batch",
        "platform": "51job",
        "title": "AI PM",
        "company": "ACME",
        "location": "深圳",
        "salary_str": "30-50K",
        "industry_tag": "互联网",
        "function_tag": "产品",
        "position_tag": "AI产品经理",
        "parsed_sections": {"requirements": ["LLM", "RAG", "Python"]},
        "tags": ["LLM", "RAG"],
        "crawled_at": "2026-07-04T00:00:00+00:00",
    }
    base.update(overrides)
    return base


def test_jd_platform_label_known_sources():
    # 默认 _row platform=51job，要测其他 source 时同步改 platform
    assert page_mod_1._jd_platform_label(_row(source="51job_batch", platform="51job")) == "51job"
    assert page_mod_1._jd_platform_label(_row(source="jobsdb_batch", platform="jobsdb")) == "JobsDB"
    assert page_mod_1._jd_platform_label(_row(source="liepin_batch", platform="liepin")) == "猎聘"
    assert page_mod_1._jd_platform_label(_row(source="manual", platform="")) == "其他"


def test_jd_platform_label_inferred_from_platform_field():
    assert page_mod_1._jd_platform_label(_row(source=None, platform="51job")) == "51job"
    assert page_mod_1._jd_platform_label(_row(source=None, platform="boss")) == "Boss"


def test_jd_freshness_label_recent():
    from datetime import datetime, timezone, timedelta

    now_real = datetime.now(timezone.utc)
    three_days_ago = (now_real - timedelta(days=3)).isoformat()
    assert "天前" in page_mod_1._jd_freshness_label({"crawled_at": three_days_ago})


def test_jd_freshness_label_missing_or_invalid():
    assert page_mod_1._jd_freshness_label({"crawled_at": None}) == ""
    assert page_mod_1._jd_freshness_label({"crawled_at": "garbage"}) == ""


def test_jd_salary_chip_str():
    html = page_mod_1._jd_salary_chip({"salary_str": "30-50K"})
    assert "30-50K" in html
    assert "jd-meta-chip-salary" in html


def test_jd_salary_chip_min_max_fallback():
    html = page_mod_1._jd_salary_chip({"salary_str": "", "salary_min": 30000, "salary_max": 50000})
    assert "30K-50K" in html


def test_render_jd_meta_row_includes_quality_chip():
    html = page_mod_1._render_jd_meta_row(_row(), quality_score=0.85)
    assert "51job" in html  # platform
    assert "jd-quality-chip" in html
    assert "0.85" in html
    assert "互联网" in html  # industry tag chip
    assert "📋 涵盖" in html  # requirements count
    assert "📍 深圳" in html


def test_render_jd_meta_row_handles_no_quality_score():
    html = page_mod_1._render_jd_meta_row(_row(), quality_score=None)
    assert "未评分" in html
    assert "jd-quality-na" in html


def test_lazy_score_jd_writes_back_when_missing(tmp_db):
    """没有 quality_score 时立即算并写回；已有则原样返回。"""
    row = _row(quality_score=None, salary_str="20-30K",
               parsed_sections={"requirements": ["X", "Y"]})
    # 用 db 直接写，绕过 list 路径
    jd_id = tmp_db.insert_jd(
        {
            "url": "https://example.com/test-quality",
            "title": row["title"],
            "company": row["company"],
            "source": row["source"],
            "platform": row["platform"],
            "raw_text": "this is a " * 200,  # 长文本 → richness=0.9
            "parsed_sections": row["parsed_sections"],
            "tags": row["tags"],
            "industry_tag": row["industry_tag"],
            "crawled_at": row["crawled_at"],
        }
    , user_id="test")

    fetched = tmp_db.get_jd(jd_id)
    assert fetched["quality_score"] is None

    score = page_mod_1._lazy_score_jd(tmp_db, fetched)
    assert score is not None
    assert 0 <= score <= 1

    fetched2 = tmp_db.get_jd(jd_id)
    assert fetched2["quality_score"] is not None  # 已写回


def test_lazy_score_jd_noop_when_already_scored(tmp_db):
    row = {
        "id": "x",
        "user_id": "default",
        "source": "manual",
        "raw_text": "text",
        "quality_score": 0.93,
        "parsed_sections": {},
        "tags": [],
        "crawled_at": None,
    }
    assert page_mod_1._lazy_score_jd(tmp_db, row) == 0.93  # 直接返回，不重算
