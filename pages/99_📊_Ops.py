#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M-v4-1 生产可观测性面板（Streamlit multipage 文件）。

Streamlit 自动识别 pages/ 下数字前缀文件 → sidebar 出现 "📊 Ops" 入口。
4 个 panel：
1. LLM judge mock fallback rate（红 ≥ 10% / 黄 3-10% / 绿 < 3%）
2. Retrieval 耗时（avg / p95 / count + rerank 分组）
3. LLM 调用成功率（最近 7 天）
4. Top 失败 case（operation × error_type）

数据走 services/ops_metrics.py（纯函数，单测已覆盖）。
空数据库 → 各 panel 显示 "暂无数据"，不崩。
登录门：直接读 st.session_state.user_id；未登录提示回主页登录（不写库）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st
from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from database.factory import get_db  # noqa: E402
from services.ops_metrics import (  # noqa: E402
    judge_mock_fallback_rate,
    llm_success_rate,
    retrieval_latency,
    threshold_color,
    top_failure_cases,
)


ANONYMOUS_USER_ID = "anonymous"


st.set_page_config(
    page_title="Ops · JobHunter",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _require_login() -> bool:
    """pages/99_📊_Ops.py 不走 web_app.py 路由分发，自查登录态。"""
    user_id = st.session_state.get("user_id")
    if not user_id or user_id == ANONYMOUS_USER_ID:
        st.warning("Ops 面板需要登录。请回到主页登录后再访问此页面。")
        st.stop()
        return False
    return True


def _color_badge(rate: float) -> str:
    """返回 markdown 颜色徽章。"""
    color = threshold_color(rate)
    label = f"{rate * 100:.1f}%"
    if color == "red":
        return f":red_circle: **{label}**"
    if color == "yellow":
        return f":large_orange_diamond: {label}"
    return f":large_green_circle: {label}"


def _empty(text: str = "暂无数据") -> None:
    st.info(text)


# ---------------------------------------------------------------------------
# Panel 1
# ---------------------------------------------------------------------------
def panel_judge_mock_fallback(backend) -> None:
    st.subheader("① LLM judge mock fallback rate")
    st.caption(
        "数据源：`llm_calls` 中 `operation LIKE '%judge%'` 且 `error_message` 含 "
        "`MOCK`/`FALLBACK` 的占比。最近 7 天。阈值：红 ≥10% / 黄 3-10% / 绿 <3%。"
    )
    try:
        r = judge_mock_fallback_rate(backend)
    except Exception as exc:
        st.error(f"查询失败：{exc}")
        return

    if r["total_judge_calls"] == 0:
        _empty("暂无 judge 调用记录。跑一次 `eval/run_eval.py` 或触发一次 LLM-as-judge 评分即可。")
        return

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("总 judge 调用", r["total_judge_calls"])
    with col2:
        st.metric("mock fallback 次数", r["mock_fallback_calls"])
    with col3:
        st.markdown(f"**mock fallback rate**  {_color_badge(r['mock_fallback_rate'])}")

    # 趋势图（按天）
    by_day = r["by_day"]
    if by_day:
        st.markdown("**最近 7 天趋势**")
        # 手画一个简单的 markdown 表格（不依赖 altair，避免环境问题）
        rows_md = "| 日期 | 总调用 | mock | 比例 |\n|------|-------|------|------|"
        for d in by_day:
            rate = (d["mock"] / d["total"]) if d["total"] else 0.0
            rows_md += f"\n| {d['day']} | {d['total']} | {d['mock']} | {_color_badge(rate)} |"
        st.markdown(rows_md)


# ---------------------------------------------------------------------------
# Panel 2
# ---------------------------------------------------------------------------
def panel_retrieval_latency(backend) -> None:
    st.subheader("② Retrieval 耗时")
    st.caption(
        "数据源：`quality_checks` 中 `check_type='retrieval'`（旧代码曾混用 `llm_call`）"
        "，`details.latency_ms` 字段。SQLite 无 percentile_cont → P95 显示 N/A。"
    )
    try:
        r = retrieval_latency(backend)
    except Exception as exc:
        st.error(f"查询失败：{exc}")
        return

    if r["count"] == 0:
        _empty("暂无 retrieval/llm_call 延迟记录。先做几次匹配 / 改写即可。")
        return

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("调用次数", r["count"])
    with col2:
        st.metric("平均延迟 (ms)", f"{r['avg_ms']:.0f}")
    with col3:
        p95_text = f"{r['p95_ms']:.0f}" if r["p95_ms"] is not None else "N/A (SQLite)"
        st.metric("P95 (ms)", p95_text)

    if r["by_phase"]:
        st.markdown("**按 phase（details.rerank 标记）分组**")
        rows_md = "| phase | count | avg_ms |\n|-------|-------|--------|"
        for p in r["by_phase"]:
            rows_md += f"\n| `{p['phase']}` | {p['count']} | {p['avg_ms']:.0f} |"
        st.markdown(rows_md)


# ---------------------------------------------------------------------------
# Panel 3
# ---------------------------------------------------------------------------
def panel_llm_success_rate(backend) -> None:
    st.subheader("③ LLM 调用成功率")
    st.caption(
        "数据源：`llm_calls.status` 最近 7 天。`success` + `cache_hit` 都算成功；"
        "`error` 算失败。阈值：≥99% 绿 / 95-99% 黄 / <95% 红（口径由你定）。"
    )
    try:
        r = llm_success_rate(backend, days=7)
    except Exception as exc:
        st.error(f"查询失败：{exc}")
        return

    if r["total"] == 0:
        _empty("暂无 LLM 调用记录。")
        return

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("总调用", r["total"])
    col2.metric("success", r["success"])
    col3.metric("error", r["error"])
    col4.metric("cache_hit", r["cache_hit"])

    st.markdown(f"**成功率（含 cache_hit）**  {_color_badge(r['success_rate'])}")
    st.markdown(f"**失败率**  {_color_badge(r['error_rate'])}")


# ---------------------------------------------------------------------------
# Panel 4
# ---------------------------------------------------------------------------
def panel_top_failure_cases(backend) -> None:
    st.subheader("④ Top 失败 case")
    st.caption(
        "数据源：`llm_calls` 中 `status='error'`，按 (operation, error_type) "
        "分组统计，倒序 Top 10。最近 7 天。"
    )
    try:
        rows = top_failure_cases(backend, days=7, limit=10)
    except Exception as exc:
        st.error(f"查询失败：{exc}")
        return

    if not rows:
        _empty("最近 7 天无失败调用，太棒了！")
        return

    rows_md = "| 排名 | operation | error_type | count |\n|------|-----------|------------|-------|"
    for i, row in enumerate(rows, 1):
        rows_md += f"\n| {i} | `{row['operation']}` | `{row['error_type']}` | {row['count']} |"
    st.markdown(rows_md)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    st.title("📊 Ops 可观测性面板")
    st.caption(
        "M-v4-1 — 4 个核心 panel，所有指标走 `database/factory.py::get_db()`，"
        "SQLite / PostgreSQL 自动适配。环境变量 `OPS_DASHBOARD_ENABLED` 控制可见性（默认 true）。"
    )

    # 环境开关
    if os.environ.get("OPS_DASHBOARD_ENABLED", "true").lower() not in ("1", "true", "yes"):
        st.error("Ops 面板已通过 `OPS_DASHBOARD_ENABLED=false` 关闭。")
        st.stop()

    _require_login()

    try:
        backend = get_db()
    except Exception as exc:
        st.error(f"无法连接数据库：{exc}")
        st.stop()

    # 顶部刷新按钮
    if st.button("🔄 刷新数据", use_container_width=False):
        st.rerun()

    panel_judge_mock_fallback(backend)
    st.divider()
    panel_retrieval_latency(backend)
    st.divider()
    panel_llm_success_rate(backend)
    st.divider()
    panel_top_failure_cases(backend)


main()
