#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M-v4-1 web_app 拆分 — JD 库：用户 / 公共 JD 浏览 + 维护 + 评分。

来源：web_app.py 原 render_jd_library() + _PLATFORM_LABEL + _SOURCE_TO_PLATFORM +
_jd_platform_label + _jd_freshness_label + _jd_salary_chip + _render_jd_meta_row +
_lazy_score_jd + _short_time + jd_to_db_payload（05 也有，1:1 复制）。

Streamlit multipage 自动识别 → sidebar 出现 "📚 JD Library" 入口。
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st  # noqa: E402

from web_app import (  # noqa: E402
    init_session_state,
    init_app_services,
    render_top_nav,
    run_async,
    current_user_id,
)
from services.text_limits import MAX_USER_TEXT_CHARS, clamp_user_text  # noqa: E402

st.set_page_config(
    page_title="JobHunter · JD 库",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ---------------------------------------------------------------------------
# JD metadata helpers (M11 / PR2) — 原文搬迁
# ---------------------------------------------------------------------------

_PLATFORM_LABEL = {
    "51job": "51job",
    "jobsdb": "JobsDB",
    "liepin": "猎聘",
    "boss": "Boss",
    "zhilian": "智联",
}
_SOURCE_TO_PLATFORM = {
    "51job_batch": "51job",
    "jobsdb_batch": "jobsdb",
    "liepin_batch": "liepin",
    "smart_collector": "liepin",
    "crawler": "liepin",
    "jd_crawler": "liepin",
    "manual": "manual",
    "pdf": "manual",
    "url": "manual",
}


def _jd_platform_label(jd: Dict) -> str:
    """从 platform 字段或 source 反推中文平台名。"""
    plat = jd.get("platform") or _SOURCE_TO_PLATFORM.get(jd.get("source", ""), "")
    return _PLATFORM_LABEL.get(plat, "其他")


def _jd_freshness_label(jd: Dict) -> str:
    """crawled_at → "5 天前 / 3 个月前"，没有就空。"""
    ts = jd.get("crawled_at")
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return ""
    now = datetime.now(timezone.utc)
    days = max(0, int((now - dt).days))
    if days < 1:
        return "今天"
    if days < 30:
        return f"{days} 天前"
    if days < 365:
        return f"{days // 30} 个月前"
    return f"{days // 365} 年前"


def _jd_salary_chip(jd: Dict) -> str:
    sal = (jd.get("salary_str") or "").strip()
    if sal:
        return f'<span class="jd-meta-chip jd-meta-chip-salary">💰 {sal}</span>'
    smin = jd.get("salary_min")
    smax = jd.get("salary_max")
    if smin or smax:
        if smin and smax:
            text = f"{smin // 1000}K-{smax // 1000}K"
        elif smin:
            text = f"≥{smin // 1000}K"
        else:
            text = f"≤{smax // 1000}K"
        return f'<span class="jd-meta-chip jd-meta-chip-salary">💰 {text}</span>'
    return ""


def _render_jd_meta_row(jd: Dict, quality_score: Optional[float]) -> str:
    chips: List[str] = []

    platform_label = _jd_platform_label(jd)
    if platform_label and platform_label != "其他":
        chips.append(f'<span class="jd-meta-chip jd-meta-chip-platform">{platform_label}</span>')

    fresh = _jd_freshness_label(jd)
    if fresh:
        chips.append(f'<span class="jd-meta-chip">🕐 {fresh}</span>')

    loc = (jd.get("location") or "").strip()
    if loc:
        chips.append(f'<span class="jd-meta-chip jd-meta-chip-location">📍 {loc}</span>')

    salary = _jd_salary_chip(jd)
    if salary:
        chips.append(salary)

    for tag_key in ("industry_tag", "function_tag", "position_tag"):
        tag_val = (jd.get(tag_key) or "").strip()
        if tag_val:
            chips.append(f'<span class="jd-meta-chip jd-meta-chip-tag">{tag_val}</span>')

    parsed = jd.get("parsed_sections") or {}
    n_req = len(parsed.get("requirements") or []) if isinstance(parsed, dict) else 0
    if n_req > 0:
        chips.append(f'<span class="jd-meta-chip">📋 涵盖 {n_req} 项要求</span>')

    from services.jd_quality_service import quality_label
    if quality_score is not None:
        label = quality_label(quality_score)
        cls_map = {"★★★★": "jd-quality-4", "★★★": "jd-quality-3", "★★": "jd-quality-2", "★": "jd-quality-1"}
        score_cls = cls_map.get(label, "jd-quality-na")
        text = f"数据质量 {label} · {quality_score:.2f}"
        chips.append(f'<span class="jd-quality-chip {score_cls}">{text}</span>')
    else:
        chips.append('<span class="jd-quality-chip jd-quality-na">数据质量 未评分</span>')

    return " ".join(chips) if chips else ""


def _lazy_score_jd(db: Any, jd: Dict) -> Optional[float]:
    """若 jd 没有 quality_score，立即计算并写回。返回 score 或 None。"""
    if jd.get("quality_score") is not None:
        return jd["quality_score"]
    try:
        from services.jd_quality_service import compute_jd_quality

        result = compute_jd_quality(jd)
        now_iso = datetime.now(timezone.utc).isoformat()
        db.update_jd_quality_score(jd["id"], result["composite"], now_iso)
        return result["composite"]
    except Exception:
        return None


def _short_time(iso: Optional[str]) -> str:
    if not iso:
        return ""
    return iso.replace("T", " ")[:16]


def jd_to_db_payload(
    jd_text: str, jd_result: Dict[str, Any], user_id: str, source: str = "manual",
) -> Dict[str, Any]:
    return {
        "user_id": user_id,
        "title": jd_result.get("title", ""),
        "company": jd_result.get("company", ""),
        "location": jd_result.get("location", ""),
        "raw_text": jd_text,
        "parsed_sections": {
            "responsibilities": jd_result.get("responsibilities", []) or jd_result.get("core_requirements", []) or [],
            "requirements": jd_result.get("requirements", []) or jd_result.get("core_requirements", []) or [],
        },
        "tags": jd_result.get("keywords", []) or jd_result.get("tags", []) or [],
        "source": source,
    }


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------


def render_jd_library() -> None:
    from services.audit_service import log_action
    from services.jd_library_service import (
        JdLibraryError,
        cleanup_garbage_public_jds,
        count_visible_jds,
        delete_user_jd,
        ensure_public_seed_jds,
        insert_user_jd,
        list_sources,
        list_visible_jds,
    )
    from tools.jd_indexer import embed_and_store_jd_chunks
    from tools.scraper.jd_analyzer_enhanced import JDAnalyzerEnhanced

    render_top_nav()
    st.header("JD库")
    st.caption("这里保存你上传过的 JD，也能看到之前爬取的公共种子 JD。")

    user_id = current_user_id()
    try:
        changed = ensure_public_seed_jds(st.session_state.db)
        if changed:
            st.toast(f"已将 {changed} 条历史爬取 JD 标记为公共种子库。")
    except Exception as exc:
        st.warning(f"公共 JD 初始化失败：{exc}")

    with st.expander("添加 JD 到我的 JD库"):
        jd_text = st.text_area("粘贴 JD", height=220, max_chars=MAX_USER_TEXT_CHARS, key="jd_library_add_text")
        if st.button("分析并保存到 JD库", disabled=not jd_text):
            if not require_services_safe():
                return
            jd_text, truncated = clamp_user_text(jd_text)
            if truncated:
                st.warning(f"JD 超过 {MAX_USER_TEXT_CHARS} 字符，已截断后分析。建议只粘贴职责/要求正文。")
            with st.spinner("正在分析并保存 JD..."):
                analyzer = JDAnalyzerEnhanced(llm_client=st.session_state.llm_client)
                jd_result = run_async(analyzer.parse_from_text(jd_text))
                jd_payload = jd_to_db_payload(jd_text, jd_result, user_id, source="manual")
                jd_id = insert_user_jd(st.session_state.db, user_id, jd_payload)
                embed_and_store_jd_chunks(st.session_state.db, jd_id, jd_text, user_id=user_id)
                log_action(
                    st.session_state.db,
                    user_id=user_id,
                    action="jd.create",
                    target_table="jds",
                    target_id=jd_id,
                    details={"flow": "jd_library", "source": "manual"},
                )
                st.success("已保存到 JD库。")

    col_s, col_f = st.columns([2, 1])
    with col_s:
        search = st.text_input("搜索 JD", placeholder="职位、公司、关键词")
    with col_f:
        sources = ["全部"] + list_sources(st.session_state.db, user_id)
        source = st.selectbox("来源", sources)

    source_filter = None if source == "全部" else source
    total = count_visible_jds(
        st.session_state.db,
        user_id,
        search=search or None,
        source=source_filter,
    )
    page_options = [10, 25, 50]
    page_col, size_col, nav_col = st.columns([1, 1, 2])
    with size_col:
        page_size = st.selectbox(
            "每页数量",
            page_options,
            index=page_options.index(st.session_state.jd_library_page_size) if st.session_state.jd_library_page_size in page_options else 1,
        )
    if page_size != st.session_state.jd_library_page_size:
        st.session_state.jd_library_page_size = page_size
        st.session_state.jd_library_page = 1
        st.rerun()

    max_page = max(1, (total + st.session_state.jd_library_page_size - 1) // st.session_state.jd_library_page_size)
    st.session_state.jd_library_page = min(st.session_state.jd_library_page, max_page)
    with page_col:
        st.metric("可见 JD", total)
    with nav_col:
        prev_col, page_info_col, next_col = st.columns([1, 2, 1])
        with prev_col:
            if st.button("上一页", disabled=st.session_state.jd_library_page <= 1):
                st.session_state.jd_library_page -= 1
                st.rerun()
        with page_info_col:
            st.caption(f"第 {st.session_state.jd_library_page}/{max_page} 页")
        with next_col:
            if st.button("下一页", disabled=st.session_state.jd_library_page >= max_page):
                st.session_state.jd_library_page += 1
                st.rerun()

    rows = list_visible_jds(
        st.session_state.db,
        user_id,
        search=search or None,
        source=source_filter,
        limit=st.session_state.jd_library_page_size,
        offset=(st.session_state.jd_library_page - 1) * st.session_state.jd_library_page_size,
    )

    with st.expander("JD库维护：扫描废数据"):
        st.caption("只扫描公共爬取来源，并用软删除处理高置信登录/验证码/人机验证页面。")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("扫描疑似废数据"):
                st.session_state.jd_garbage_preview = cleanup_garbage_public_jds(st.session_state.db, dry_run=True)
        with c2:
            if st.button("软删除高置信废数据", disabled=not st.session_state.jd_garbage_preview):
                removed = cleanup_garbage_public_jds(st.session_state.db, dry_run=False)
                st.session_state.jd_garbage_preview = []
                st.success(f"已软删除 {len(removed)} 条高置信废数据。")
                st.rerun()
        preview = st.session_state.jd_garbage_preview
        if preview:
            st.warning(f"扫描到 {len(preview)} 条疑似废数据。")
            for item in preview[:10]:
                st.caption(f"{item.get('title') or '未命名'} · {item.get('source')} · {item.get('company') or '未知公司'}")

    for jd in rows:
        owned = jd.get("user_id") == user_id
        badge = '<span class="private-badge">我的 JD</span>' if owned else '<span class="public-badge">公共 JD</span>'
        q_score = jd.get("quality_score")
        if q_score is None:
            q_score = _lazy_score_jd(st.session_state.db, jd)
        meta_html = _render_jd_meta_row(jd, q_score)
        expander_label = (
            f"{jd.get('title') or '未命名'} @ {jd.get('company') or '未知公司'}"
        )
        with st.expander(expander_label):
            st.markdown(badge, unsafe_allow_html=True)
            if meta_html:
                st.markdown(meta_html, unsafe_allow_html=True)
            st.markdown(
                f'<div class="jd-summary-row">来源：{jd.get("source", "")} · '
                f'岗位标签：{jd.get("position_tag") or "未分类"}</div>',
                unsafe_allow_html=True,
            )
            st.write((jd.get("raw_text") or "")[:1200])
            c1, c2 = st.columns(2)
            with c1:
                if st.button("用于修改已有简历", key=f"use_jd_{jd['id']}"):
                    st.session_state.jd_id = jd["id"]
                    st.session_state.jd_result = {
                        "title": jd.get("title", ""),
                        "company": jd.get("company", ""),
                        "location": jd.get("location", ""),
                        "core_requirements": jd.get("parsed_sections", {}).get("requirements", []),
                        "keywords": jd.get("tags", []),
                        "raw_text": jd.get("raw_text", ""),
                    }
                    st.session_state.app_route = "flow_b"
                    st.rerun()
            with c2:
                if owned and st.button("删除", key=f"delete_jd_{jd['id']}"):
                    try:
                        delete_user_jd(st.session_state.db, user_id, jd["id"])
                        log_action(
                            st.session_state.db,
                            user_id=user_id,
                            action="jd.delete",
                            target_table="jds",
                            target_id=jd["id"],
                        )
                        st.success("已删除。")
                        st.rerun()
                    except JdLibraryError as exc:
                        st.error(str(exc))


def require_services_safe() -> bool:
    """轻量 require_services（避免跨 page import 循环）— 复用 web_app 同名函数。"""
    from web_app import require_services
    return require_services()


def main() -> None:
    init_session_state()
    init_app_services()
    render_jd_library()


if __name__ == "__main__":
    main()
