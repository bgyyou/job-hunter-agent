# -*- coding: utf-8 -*-
"""JD 质量打分：纯函数 +0 SQLite 写入辅助。

四个子分 → 加权 composite：
  parse_completeness (35%)：parsed_sections + tags + industry_tag 完整度
  source_authority   (25%)：源等级权重（51job/jobsdb 高、liepin 低、manual 中等）
  freshness          (20%)：crawled_at 距今衰减（<30d=1.0，>365d≈0）
  text_richness      (20%)：raw_text 长度分桶

garbage_jd（命中 is_garbage_jd）会被强制压到 ≤0.2。"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from services.jd_library_service import CRAWLED_SOURCES, is_garbage_jd


# 源等级权重：51job / jobsdb 主采集，liepin 已被反爬劝退（质量不稳）
_SOURCE_AUTHORITY = {
    "51job_batch": 0.90,
    "jobsdb_batch": 0.90,
    "liepin_batch": 0.70,
    "smart_collector": 0.80,
    "crawler": 0.75,
    "jd_crawler": 0.75,
    "manual": 0.85,
    "pdf": 0.85,
    "url": 0.80,
}
_DEFAULT_SOURCE_AUTHORITY = 0.70  # 未知源


def _parse_completeness(jd: Dict[str, Any]) -> float:
    """0-1 based on parsed_sections 结构化程度 + tags + industry_tag 完整度。"""
    parsed = jd.get("parsed_sections") or {}
    requirements = parsed.get("requirements") or []
    preferred = parsed.get("preferred") or []
    tags = jd.get("tags") or []
    industry_tag = jd.get("industry_tag")

    score = 0.0
    if requirements:
        score += 0.35
    if preferred:
        score += 0.10
    if tags:
        score += 0.20 + min(0.20, len(tags) * 0.04)  # cap at 0.40
    if industry_tag:
        score += 0.20
    return min(1.0, score)


def _source_authority(jd: Dict[str, Any]) -> float:
    source = jd.get("source") or ""
    if jd.get("deleted_at"):
        return 0.0
    return _SOURCE_AUTHORITY.get(source, _DEFAULT_SOURCE_AUTHORITY)


def _freshness(jd: Dict[str, Any], *, now: Optional[datetime] = None) -> float:
    """Sigmoid 衰减：以 crawled_at 为锚，30 天=1.0，180 天≈0.4，>365d≈0.1。"""
    crawled_at = jd.get("crawled_at")
    if not crawled_at:
        # 未爬取/手动无时间戳 → 默认中等
        return 0.5
    try:
        ts = datetime.fromisoformat(str(crawled_at).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return 0.5
    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    days = max(0.0, (ref - ts).total_seconds() / 86400.0)
    # 以 90 天为半衰期的 sigmoid
    return round(1.0 / (1.0 + math.exp((days - 90.0) / 30.0)), 4)


def _text_richness(jd: Dict[str, Any]) -> float:
    raw_text = (jd.get("raw_text") or "").strip()
    length = len(raw_text)
    if length < 200:
        return 0.20
    if length < 500:
        return 0.40
    if length < 1500:
        return 0.70
    if length < 3500:
        return 0.90
    return 1.0


def compute_jd_quality(jd: Dict[str, Any], *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """返回 4 个子分 + composite 的 0-1 分 dict。

    返回结构：`{parse_completeness, source_authority, freshness, text_richness, composite, is_garbage}`
    """
    subscores = {
        "parse_completeness": round(_parse_completeness(jd), 4),
        "source_authority": round(_source_authority(jd), 4),
        "freshness": _freshness(jd, now=now),
        "text_richness": round(_text_richness(jd), 4),
    }
    composite_raw = (
        0.35 * subscores["parse_completeness"]
        + 0.25 * subscores["source_authority"]
        + 0.20 * subscores["freshness"]
        + 0.20 * subscores["text_richness"]
    )

    garbage = is_garbage_jd(jd) if (jd.get("source") or "") in CRAWLED_SOURCES else False
    composite = min(0.20, composite_raw) if garbage else round(composite_raw, 4)

    return {
        **subscores,
        "composite": composite,
        "is_garbage": garbage,
    }


def quality_label(composite: Optional[float]) -> str:
    """0-1 分 → 4/3/2/1 星中文标签，供 UI 渲染。

    阈值根据首批 4482 条回填分布确定：
    - 0.30 以下：垃圾 / 几乎无 metadata
    - 0.30-0.50：已爬取未深入分析（典型 51job_batch）
    - 0.50-0.70：结构化良好（典型 jobsdb_batch）
    - ≥0.70：高质量 / 人工完善
    """
    if composite is None:
        return "未评分"
    if composite >= 0.70:
        return "★★★★"
    if composite >= 0.50:
        return "★★★"
    if composite >= 0.30:
        return "★★"
    return "★"
