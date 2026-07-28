#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Job Hunter product UI (Streamlit)."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st
from dotenv import load_dotenv
from loguru import logger

# v2.1 P2-1 阶段一：internal beta 模式 — internal_keys.json 存在则优先注入
# 必须在 load_dotenv 之前：load_dotenv 不覆盖已存在的 env var
# 这保证 internal_key 比 .env 默认值优先（用户 .env 显式配置仍可覆盖 internal）
try:
    from config.internal_keys import apply_internal_keys, is_internal_beta_active
    if is_internal_beta_active():
        applied, src = apply_internal_keys()
        if applied:
            logger.info(f"JobHunter started in internal beta mode (key from {src})")
except Exception as _exc:
    logger.debug(f"internal_keys helper not available: {_exc}")

load_dotenv()

from config.settings import settings
from database.factory import get_db
from loguru import logger
from services.audit_service import log_action
from services.auth_service import AuthError, AuthService
from services.flow_a_draft_service import FlowADraftService
from services.jd_library_service import ensure_public_seed_jds
from services.quota_service import QuotaExceededError, QuotaService
from tools.llm import OpenAICompatibleClient

settings.setup_logging()

# v4 T1.1：登录门已接线 AuthService；主流程必须登录。
# ANONYMOUS_USER_ID 仅作未登录兜底（landing / privacy / terms 等公开页不写库）。
ANONYMOUS_USER_ID = "anonymous"

st.set_page_config(
    page_title="JobHunter",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
<style>
/* ============ GLOBAL THEME: DEEP PURPLE NEON ============ */
section[data-testid="stMain"] {
    background: #0a0a0f !important;
}
section[data-testid="stMain"] > div {
    background: #0a0a0f !important;
    padding-top: 1.2rem !important;
    padding-bottom: 3rem !important;
    max-width: 1180px !important;
}

/* Hide Streamlit chrome (Deploy button, toolbar, header, sidebar toggle) */
div[data-testid="stSidebar"],
div[data-testid="stSidebarCollapsedControl"],
header[data-testid="stHeader"],
div[data-testid="stToolbar"],
div[data-testid="stDecoration"],
div[data-testid="stStatusWidget"] {
    display: none !important;
}

/* Text colors */
section[data-testid="stMain"] p,
section[data-testid="stMain"] span,
section[data-testid="stMain"] li,
section[data-testid="stMain"] label {
    color: #cbd5e1 !important;
}
section[data-testid="stMain"] h1,
section[data-testid="stMain"] h2,
section[data-testid="stMain"] h3 {
    color: #ffffff !important;
    letter-spacing: -0.02em;
}
section[data-testid="stMain"] h4 {
    color: #c4b5fd !important;
    letter-spacing: -0.02em;
}
section[data-testid="stMain"] h5 {
    color: #a78bfa !important;
    letter-spacing: -0.02em;
}
section[data-testid="stMain"] [data-testid="stCaptionContainer"],
section[data-testid="stMain"] .st-emotion-cache-14pd4lc,
section[data-testid="stMain"] [data-testid="stWidgetLabel"] p {
    color: #a78bfa !important;
}

/* ============ CUSTOM CLASSES ============ */
.choice-card {
    background: #1a0b2e;
    border: 1px solid rgba(139, 92, 246, 0.25);
    border-radius: 14px;
    padding: 2rem;
    height: 100%;
    transition: transform 0.25s ease, border-color 0.25s ease, box-shadow 0.25s ease;
}
.choice-card:hover {
    border-color: rgba(139, 92, 246, 0.55);
    box-shadow: 0 12px 35px rgba(139, 92, 246, 0.2);
}
.step-pill {
    display: inline-block;
    padding: 0.35rem 0.7rem;
    border-radius: 999px;
    background: rgba(139, 92, 246, 0.25);
    color: #c4b5fd;
    font-size: 0.85rem;
    font-weight: 600;
    margin-right: 0.4rem;
    border: 1px solid rgba(139, 92, 246, 0.35);
}
.public-badge {
    display: inline-block;
    padding: 0.2rem 0.55rem;
    border-radius: 999px;
    background: rgba(139, 92, 246, 0.2);
    color: #c4b5fd;
    font-size: 0.78rem;
    border: 1px solid rgba(139, 92, 246, 0.35);
}
.private-badge {
    display: inline-block;
    padding: 0.2rem 0.55rem;
    border-radius: 999px;
    background: rgba(100, 116, 139, 0.15);
    color: #94a3b8;
    font-size: 0.78rem;
    border: 1px solid rgba(100, 116, 139, 0.25);
}

/* ============ JD META CHIPS (PR2 / M11) ============ */
.jd-meta-chip {
    display: inline-block;
    padding: 0.15rem 0.5rem;
    border-radius: 999px;
    font-size: 0.72rem;
    margin-right: 0.3rem;
    margin-bottom: 0.25rem;
    background: rgba(139, 92, 246, 0.10);
    color: #c4b5fd;
    border: 1px solid rgba(139, 92, 246, 0.25);
}
.jd-meta-chip-platform {
    background: rgba(56, 189, 248, 0.10);
    color: #38bdf8;
    border: 1px solid rgba(56, 189, 248, 0.30);
}
.jd-meta-chip-salary {
    background: rgba(250, 204, 21, 0.10);
    color: #fbbf24;
    border: 1px solid rgba(250, 204, 21, 0.30);
}
.jd-meta-chip-location {
    background: rgba(16, 185, 129, 0.10);
    color: #10b981;
    border: 1px solid rgba(16, 185, 129, 0.30);
}
.jd-meta-chip-tag {
    background: rgba(244, 114, 182, 0.08);
    color: #f472b6;
    border: 1px solid rgba(244, 114, 182, 0.25);
}
.jd-quality-chip {
    display: inline-block;
    padding: 0.15rem 0.55rem;
    border-radius: 999px;
    font-size: 0.72rem;
    font-weight: 600;
    border: 1px solid transparent;
    letter-spacing: 0.05em;
}
.jd-quality-4 {
    background: rgba(16, 185, 129, 0.18);
    color: #34d399;
    border-color: rgba(16, 185, 129, 0.45);
}
.jd-quality-3 {
    background: rgba(56, 189, 248, 0.15);
    color: #38bdf8;
    border-color: rgba(56, 189, 248, 0.40);
}
.jd-quality-2 {
    background: rgba(250, 204, 21, 0.15);
    color: #facc15;
    border-color: rgba(250, 204, 21, 0.40);
}
.jd-quality-1 {
    background: rgba(148, 163, 184, 0.18);
    color: #94a3b8;
    border-color: rgba(148, 163, 184, 0.40);
}
.jd-quality-na {
    background: rgba(148, 163, 184, 0.10);
    color: #64748b;
    border-color: rgba(148, 163, 184, 0.30);
}
.jd-summary-row {
    font-size: 0.85rem;
    color: #94a3b8;
    margin: 0.4rem 0 0.2rem 0;
}

/* ============ TOP NAV LIVE METRIC PANEL (PR4) ============ */
.topnav-metric {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 0.3rem 0.6rem;
    border-radius: 8px;
    background: rgba(139, 92, 246, 0.06);
    border: 1px solid rgba(139, 92, 246, 0.18);
    min-width: 70px;
}
.topnav-metric-num {
    font-size: 1.05rem;
    font-weight: 700;
    color: #c4b5fd;
    line-height: 1.1;
}
.topnav-metric-label {
    font-size: 0.68rem;
    color: #94a3b8;
    margin-top: 0.1rem;
}

/* ============ LANDING LIVE BAND (PR4) ============ */
.landing-live-band {
    margin-top: 1.5rem;
    margin-bottom: 0.5rem;
    padding-top: 1rem;
    border-top: 1px solid rgba(139, 92, 246, 0.25);
}
.landing-live-band-title {
    font-size: 1rem;
    color: #c4b5fd;
    text-align: center;
    letter-spacing: 0.06em;
    margin-bottom: 0.5rem;
}

/* ============ FLOW A PASTE PANEL HELP (PR5) ============ */
.step-help {
    font-size: 0.85rem;
    color: #94a3b8;
    background: rgba(139, 92, 246, 0.06);
    border-left: 3px solid rgba(139, 92, 246, 0.45);
    padding: 0.5rem 0.75rem;
    border-radius: 4px;
    margin-bottom: 0.6rem;
}

/* ============ BUTTONS ============ */
section[data-testid="stMain"] button[kind="primary"],
section[data-testid="stMain"] button[data-testid="stBaseButton-primary"] {
    background-color: #8b5cf6 !important;
    border-color: #8b5cf6 !important;
    color: #ffffff !important;
    transition: background-color 0.2s ease, transform 0.2s ease, box-shadow 0.2s ease !important;
}
section[data-testid="stMain"] button[kind="primary"]:hover,
section[data-testid="stMain"] button[data-testid="stBaseButton-primary"]:hover {
    background-color: #7c3aed !important;
    border-color: #7c3aed !important;
    transform: translateY(-1px) !important;
    box-shadow: 0 8px 25px rgba(139, 92, 246, 0.4) !important;
}
section[data-testid="stMain"] button[kind="secondary"],
section[data-testid="stMain"] button[data-testid="stBaseButton-secondary"] {
    background-color: transparent !important;
    border-color: rgba(139, 92, 246, 0.4) !important;
    color: #c4b5fd !important;
    transition: border-color 0.2s ease, color 0.2s ease !important;
}
section[data-testid="stMain"] button[kind="secondary"]:hover,
section[data-testid="stMain"] button[data-testid="stBaseButton-secondary"]:hover {
    border-color: rgba(139, 92, 246, 0.7) !important;
    color: #ffffff !important;
    background-color: rgba(139, 92, 246, 0.1) !important;
}

/* ============ INPUTS ============ */
section[data-testid="stMain"] input[type="text"],
section[data-testid="stMain"] input[type="password"],
section[data-testid="stMain"] input:not([type]),
section[data-testid="stMain"] textarea,
section[data-testid="stMain"] select {
    background-color: #0f0f17 !important;
    color: #fafafa !important;
    border-color: rgba(139, 92, 246, 0.3) !important;
    border-radius: 8px !important;
}
section[data-testid="stMain"] input:focus,
section[data-testid="stMain"] textarea:focus,
section[data-testid="stMain"] select:focus {
    border-color: #8b5cf6 !important;
    box-shadow: 0 0 0 2px rgba(139, 92, 246, 0.2) !important;
    outline: none !important;
}
section[data-testid="stMain"] input::placeholder,
section[data-testid="stMain"] textarea::placeholder {
    color: #475569 !important;
}

/* Selectbox dropdown options (rendered in portal) */
div[data-testid="stSelectboxDropdown"] {
    background-color: #1a0b2e !important;
}
div[data-testid="stSelectboxDropdown"] option,
div[data-testid="stSelectboxDropdown"] li {
    color: #fafafa !important;
}

/* ============ FORMS ============ */
section[data-testid="stMain"] [data-testid="stForm"] {
    background: #1a0b2e !important;
    border: 1px solid rgba(139, 92, 246, 0.25) !important;
    border-radius: 14px !important;
    padding: 1.5rem !important;
}

/* ============ EXPANDERS ============ */
section[data-testid="stMain"] [data-testid="stExpander"] {
    background: #1a0b2e !important;
    border: 1px solid rgba(139, 92, 246, 0.25) !important;
    border-radius: 12px !important;
    overflow: hidden;
}
section[data-testid="stMain"] [data-testid="stExpander"] summary,
section[data-testid="stMain"] [data-testid="stExpanderDetails"] {
    background: transparent !important;
    color: #c4b5fd !important;
}
section[data-testid="stMain"] [data-testid="stExpanderDetails"] p,
section[data-testid="stMain"] [data-testid="stExpanderDetails"] span,
section[data-testid="stMain"] [data-testid="stExpanderDetails"] li {
    color: #cbd5e1 !important;
}

/* ============ TABS ============ */
section[data-testid="stMain"] [data-testid="stTabs"] {
    background: transparent !important;
}
section[data-testid="stMain"] [data-testid="stTabList"] button {
    color: #94a3b8 !important;
    border-bottom: 2px solid transparent !important;
}
section[data-testid="stMain"] [data-testid="stTabList"] button[aria-selected="true"] {
    color: #ffffff !important;
    border-bottom-color: #8b5cf6 !important;
}
section[data-testid="stMain"] [data-testid="stTabList"] button:hover {
    color: #c4b5fd !important;
}

/* ============ ALERTS (dark theme, keep semantic icon) ============ */
section[data-testid="stMain"] [data-testid="stAlert"] {
    background-color: #1a0b2e !important;
    border: 1px solid rgba(139, 92, 246, 0.25) !important;
    border-radius: 12px !important;
    color: #cbd5e1 !important;
}
section[data-testid="stMain"] [data-testid="stAlert"] [data-testid="stAlertContent"] p {
    color: #cbd5e1 !important;
}

/* ============ SPINNER ============ */
section[data-testid="stMain"] [data-testid="stSpinner"] p {
    color: #c4b5fd !important;
}

/* ============ PROGRESS ============ */
section[data-testid="stMain"] [data-testid="stProgress"] > div > div {
    background-color: #8b5cf6 !important;
}

/* ============ METRIC ============ */
section[data-testid="stMain"] [data-testid="stMetric"] {
    background: #1a0b2e !important;
    border: 1px solid rgba(139, 92, 246, 0.25) !important;
    border-radius: 12px !important;
    padding: 1rem !important;
}
section[data-testid="stMain"] [data-testid="stMetric"] label,
section[data-testid="stMain"] [data-testid="stMetric"] [data-testid="stMetricLabel"] {
    color: #94a3b8 !important;
}
section[data-testid="stMain"] [data-testid="stMetric"] [data-testid="stMetricValue"] {
    color: #ffffff !important;
}

/* ============ JSON ============ */
section[data-testid="stMain"] [data-testid="stJson"] {
    background: #0f0f17 !important;
    border: 1px solid rgba(139, 92, 246, 0.25) !important;
    border-radius: 8px !important;
    color: #cbd5e1 !important;
}
section[data-testid="stMain"] [data-testid="stJson"] .styled-json-container,
section[data-testid="stMain"] [data-testid="stJson"] span {
    color: #cbd5e1 !important;
}

/* ============ DIVIDER ============ */
section[data-testid="stMain"] hr,
section[data-testid="stMain"] [data-testid="stDivider"] {
    border-color: rgba(139, 92, 246, 0.18) !important;
    background-color: rgba(139, 92, 246, 0.18) !important;
}

/* ============ CHAT ============ */
section[data-testid="stMain"] [data-testid="stChatMessage"] {
    background: #1a0b2e !important;
    border: 1px solid rgba(139, 92, 246, 0.25) !important;
    border-radius: 14px !important;
}
section[data-testid="stMain"] [data-testid="stChatMessage"] p,
section[data-testid="stMain"] [data-testid="stChatMessage"] span,
section[data-testid="stMain"] [data-testid="stChatMessage"] li {
    color: #cbd5e1 !important;
}
section[data-testid="stMain"] [data-testid="stChatInput"] {
    background: #0f0f17 !important;
    border-color: rgba(139, 92, 246, 0.3) !important;
    border-radius: 12px !important;
}
section[data-testid="stMain"] [data-testid="stChatInput"] textarea {
    background-color: #0f0f17 !important;
    color: #fafafa !important;
}

/* ============ FILE UPLOADER ============ */
section[data-testid="stMain"] [data-testid="stFileUploader"] {
    background: #1a0b2e !important;
    border: 1px dashed rgba(139, 92, 246, 0.4) !important;
    border-radius: 12px !important;
    padding: 1rem !important;
}

/* ============ DIALOG (for later, prep CSS now) ============ */
[data-testid="stDialog"] {
    background: #1a0b2e !important;
    border: 1px solid rgba(139, 92, 246, 0.4) !important;
    border-radius: 14px !important;
}
[data-testid="stDialog"] h2,
[data-testid="stDialog"] h3 {
    color: #ffffff !important;
}
[data-testid="stDialog"] p,
[data-testid="stDialog"] span,
[data-testid="stDialog"] label {
    color: #cbd5e1 !important;
}
[data-testid="stDialog"] input[type="text"],
[data-testid="stDialog"] input[type="password"] {
    background-color: #0f0f17 !important;
    color: #fafafa !important;
    border-color: rgba(139, 92, 246, 0.3) !important;
    border-radius: 8px !important;
}

/* ============ TOP NAV ============ */
.topnav-title {
    font-size: 1.3rem;
    font-weight: 800;
    color: #ffffff;
    text-shadow: 0 0 12px rgba(139, 92, 246, 0.5);
    letter-spacing: -0.02em;
}
.topnav-account {
    color: #a78bfa;
    font-size: 0.85rem;
}
.topnav-divider {
    border: none;
    border-top: 1px solid rgba(139, 92, 246, 0.18);
    margin: 0.6rem 0 1.5rem 0;
}

/* ============ BORDER CONTAINER (choice cards) ============ */
section[data-testid="stMain"] [data-testid="stVerticalBlockBorder"] {
    background: #1a0b2e !important;
    border: 1px solid rgba(139, 92, 246, 0.25) !important;
    border-radius: 14px !important;
    padding: 2rem !important;
    height: 100% !important;
    transition: transform 0.25s ease, border-color 0.25s ease, box-shadow 0.25s ease;
}
section[data-testid="stMain"] [data-testid="stVerticalBlockBorder"]:hover {
    border-color: rgba(139, 92, 246, 0.55) !important;
    box-shadow: 0 12px 35px rgba(139, 92, 246, 0.2) !important;
}
</style>
""",
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Session / services
# ---------------------------------------------------------------------------


def run_async(coro):
    """跑异步 LLM 调用。v4 T1.4：所有用户触发的 LLM 动作都经此漏斗，
    配额检查在这里统一执行（超限 → 友好提示 + st.stop 中止本次动作）。"""
    _check_llm_quota_or_stop()
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _check_llm_quota_or_stop() -> None:
    """v4 T1.4：LLM 动作前查配额。配额服务自身故障不阻塞业务（debug 日志）。"""
    try:
        db = st.session_state.get("db")
        if not db:
            return
        QuotaService(db).check_quota(current_user_id())
    except QuotaExceededError as exc:
        st.warning(str(exc))
        st.stop()
    except Exception as exc:
        logger.debug(f"quota check skipped: {exc}")


def init_session_state() -> None:
    defaults = {
        "app_route": "landing",
        # v4 T1.1：登录态。None = 未登录（只能看 landing / privacy / terms）
        "user_id": None,
        "user_display_name": None,
        "services_ready": False,
        "llm_init_error": None,
        "llm_client": None,
        "agent": None,
        "db": None,
        "resume_data": None,
        "resume_id": None,
        "jd_result": None,
        "jd_id": None,
        "match_result": None,
        "last_match_id": None,
        "last_opt_ids": [],
        "last_match_score": None,
        "optimized_resume": None,
        "optimized_resume_html": None,
        "cover_letter": None,
        "flow_b_step": "resume",
        "flow_b_company_name": "",
        "flow_b_jd_input_type": "粘贴 JD",
        # v3 round-2 (M-rebuild-1+2+3) 5-step state machine
        "fa_step": 1,                         # 1-5: JD 输入 / 表单 / 改写 / 预览 / 导出
        "fa_jd_input_mode": "rag",            # "rag" / "text" / "image"
        "fa_jd_text_input": "",               # 粘贴的 JD 原文
        "fa_jd_image_path": None,             # 上传图片的临时路径
        "fa_jd_structured": None,             # JDParserRouter 输出的 StructuredJD（dict）
        "fa_jd_review_done": False,           # 用户是否确认过（OCR 必走，RAG/text 可跳过）
        "fa_jd_industry": None,               # 由 RAG 路径填的 industry/function/level（兼容旧 fa_industry 等）
        "fa_jd_function": None,
        "fa_jd_level": None,
        # v3 round-3 (P1-2) Step 3 改写状态机：首次跑 / 重跑区分
        "fa_step3_mode": "auto",              # 当前选中的模式（auto / A / B）
        "fa_step3_first_run": True,           # True=首次跑按钮显示"改写/生成"，False=显示"重跑改写"
        "fa_step3_rewrites": None,            # 上次改写结果（list[dict]）
        "fa_step3_final_resume": None,        # 上次合并后的 final_resume（dict，供 Step 4/5 用）
        # 兼容旧 v2.1 flow_a state keys
        "fa_industry": None,
        "fa_function": None,
        "fa_position": None,
        "fa_draft_id": None,
        "fa_generation_state": {},
        "fa_last_error": None,
        "fa_incomplete_confirm_section": None,
        "fa_incomplete_missing": [],
        "fa_messages": [],
        "fa_chat_done": False,
        "fa_resume_data": None,
        "fa_resume_md": None,
        "fa_resume_html": None,
        "fa_resume_pdf": None,
        "fa_skeleton": None,
        "fa_pdf_status": None,  # PR6: None / "pending" / "ready" / "failed"
        "fa_section_index": 0,
        "fa_section_data": {},
        "fa_section_messages": {},
        "fa_section_done": [],
        "fa_section_skipped": [],
        "fa_basic_form_done": False,
        "jd_library_page": 1,
        "jd_library_page_size": 25,
        "flow_b_jd_page": 1,
        "flow_b_jd_page_size": 25,
        "jd_garbage_preview": [],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def init_app_services() -> None:
    if st.session_state.db is None:
        # v4 T1.1：走 factory，DATABASE_URL=postgresql:// 时自动切 PG 后端
        st.session_state.db = get_db()
        try:
            ensure_public_seed_jds(st.session_state.db)
        except Exception as exc:
            logger.warning(f"public JD seed setup failed: {exc}")

    if st.session_state.services_ready or st.session_state.llm_init_error:
        return

    if not settings.llm_api_key or not settings.llm_base_url or not settings.llm_model:
        st.session_state.services_ready = False
        st.session_state.llm_init_error = "AI 服务未配置，请先在环境变量中配置 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL。"
        return

    try:
        llm_client = OpenAICompatibleClient(
            api_key=settings.llm_api_key,
            api_url=settings.llm_base_url.rstrip("/"),
            model=settings.llm_model,
            is_coding_api=False,
            use_anthropic_format=settings.llm_use_anthropic_format,
            user_id=current_user_id(),  # v4 T1.4：llm_calls 埋点归属到具体用户（配额统计口径）
        )
        st.session_state.llm_client = llm_client
        st.session_state.agent = CoordinatorAgent(llm_client=llm_client)
        st.session_state.services_ready = True
        st.session_state.llm_init_error = None
    except Exception as exc:
        st.session_state.services_ready = False
        st.session_state.llm_init_error = f"AI 服务初始化失败：{exc}"


def current_user_id() -> str:
    """v4 T1.1：返回当前登录用户 id；未登录兜底 anonymous。

    登录门（文件尾部路由分发处）保证业务页面只在登录后渲染，
    所以业务写库路径拿到的都是真实 user_id。
    """
    return st.session_state.get("user_id") or ANONYMOUS_USER_ID


def _auth_service() -> AuthService:
    return AuthService(st.session_state.db)


def _apply_login_session(user: Dict[str, Any]) -> None:
    """登录/注册成功后写身份态。v4 T1.4：同时把 llm_client 的埋点归属切到真实用户。"""
    st.session_state.user_id = user["id"]
    st.session_state.user_display_name = user.get("name") or user.get("email") or user.get("phone")
    st.session_state.app_route = "mode_select"
    if st.session_state.get("llm_client") is not None:
        st.session_state.llm_client.user_id = user["id"]


def logout_user() -> None:
    """登出：清身份态，回 landing。业务草稿 state 保留在服务端 session，下次登录还在。"""
    for key in ["user_id", "user_display_name"]:
        st.session_state[key] = None
    st.session_state.app_route = "landing"


def render_auth_page() -> None:
    """v4 T1.1：登录 / 注册页。未登录访问任何业务路由时渲染。"""
    st.markdown("<h2 style='text-align:center;margin-top:3rem;'>登录 JobHunter</h2>", unsafe_allow_html=True)
    st.markdown(
        "<p style='text-align:center;color:#94a3b8;'>登录后你的简历、JD 库和改写历史只对你可见</p>",
        unsafe_allow_html=True,
    )
    _, center, _ = st.columns([1, 2, 1])
    with center:
        tab_login, tab_register = st.tabs(["登录", "注册"])

        with tab_login:
            with st.form("login_form"):
                identifier = st.text_input("邮箱或手机号", key="login_identifier")
                password = st.text_input("密码", type="password", key="login_password")
                submitted = st.form_submit_button("登录", use_container_width=True)
            if submitted:
                try:
                    user = _auth_service().login_user(identifier=identifier, password=password)
                    _apply_login_session(user)
                    st.rerun()
                except AuthError as exc:
                    st.error(str(exc))
                except Exception as exc:
                    logger.warning(f"login failed unexpectedly: {exc}")
                    st.error("登录服务暂时不可用，请稍后再试。")

        with tab_register:
            with st.form("register_form"):
                reg_name = st.text_input("昵称（可选）", key="reg_name")
                reg_email = st.text_input("邮箱", key="reg_email")
                reg_phone = st.text_input("手机号（可选，与邮箱至少填一个）", key="reg_phone")
                reg_password = st.text_input("密码（至少 8 位）", type="password", key="reg_password")
                reg_password2 = st.text_input("确认密码", type="password", key="reg_password2")
                reg_submitted = st.form_submit_button("注册并登录", use_container_width=True)
            if reg_submitted:
                if reg_password != reg_password2:
                    st.error("两次输入的密码不一致")
                else:
                    try:
                        user = _auth_service().register_user(
                            password=reg_password,
                            email=reg_email or None,
                            phone=reg_phone or None,
                            name=reg_name,
                        )
                        _apply_login_session(user)
                        st.rerun()
                    except AuthError as exc:
                        st.error(str(exc))
                    except Exception as exc:
                        logger.warning(f"register failed unexpectedly: {exc}")
                        st.error("注册服务暂时不可用，请稍后再试。")


def require_services() -> bool:
    if st.session_state.services_ready:
        return True
    st.warning(st.session_state.llm_init_error or "AI 服务暂不可用。")
    return False


def reset_flow_a_state() -> None:
    draft_id = st.session_state.get("fa_draft_id")
    db = st.session_state.get("db")
    if draft_id and db:
        try:
            FlowADraftService(db, current_user_id()).abandon_draft(draft_id)
        except Exception as exc:
            logger.warning(f"Flow A draft abandon skipped: {exc}")
    for key in [
        "fa_industry", "fa_function", "fa_position", "fa_resume_data",
        "fa_resume_md", "fa_resume_html", "fa_resume_pdf", "fa_skeleton",
    ]:
        st.session_state[key] = None
    st.session_state.fa_draft_id = None
    st.session_state.fa_generation_state = {}
    st.session_state.fa_pdf_status = None
    st.session_state.fa_pdf_error = None
    st.session_state.fa_last_error = None
    st.session_state.fa_incomplete_confirm_section = None
    st.session_state.fa_incomplete_missing = []
    st.session_state.fa_messages = []
    st.session_state.fa_chat_done = False
    st.session_state.fa_section_index = 0
    st.session_state.fa_section_data = {}
    st.session_state.fa_section_messages = {}
    st.session_state.fa_section_done = []
    st.session_state.fa_section_skipped = []
    st.session_state.fa_basic_form_done = False
    # v3 round-2: 重置 5-step state machine + JD 输入相关
    for key in [
        "fa_jd_input_mode", "fa_jd_text_input", "fa_jd_image_path",
        "fa_jd_structured", "fa_jd_review_done",
        "fa_jd_industry", "fa_jd_function", "fa_jd_level",
    ]:
        st.session_state[key] = (
            "rag" if key == "fa_jd_input_mode"
            else "" if key == "fa_jd_text_input"
            else False if key == "fa_jd_review_done"
            else None
        )
    # v3 round-3 P1-1: 重置 Step 2-5 表单 / 改写 / 预览 / 导出相关 state
    for key in [
        "fa_step2_form",        # 表单数据（dict）
        "fa_step3_rewrites",    # 改写结果（list）
        "fa_step3_final_resume",# 最终简历（dict）
    ]:
        st.session_state[key] = None
    st.session_state.fa_step3_mode = "auto"
    st.session_state.fa_step3_first_run = True  # P1-2：区分首次跑 / 手动重跑
    st.session_state.fa_step = 1


def reset_flow_a_v3_step_state() -> None:
    """P1-1：仅重置 v3 Step 2-5 state，保留 Step 1 的 JD 选择。

    用途：Step 2 / 3 / 4 表格填了一半想清空，但保留 JD。
    不动 fa_jd_structured / fa_position 等 Step 1 state。
    """
    for key in ["fa_step2_form", "fa_step3_rewrites", "fa_step3_final_resume"]:
        st.session_state[key] = None
    st.session_state.fa_step3_mode = "auto"
    st.session_state.fa_step3_first_run = True


def reset_flow_b_state() -> None:
    for key in [
        "resume_data", "resume_id", "jd_result", "jd_id", "match_result",
        "last_match_id", "last_match_score", "optimized_resume",
        "optimized_resume_html", "cover_letter",
    ]:
        st.session_state[key] = None
    st.session_state.last_opt_ids = []
    st.session_state.flow_b_step = "resume"


def _save_flow_a_draft(
    current_step: str,
    current_section: Optional[str],
    *,
    status: str = "draft",
    last_error: Optional[str] = None,
) -> None:
    service = _flow_a_draft_service()
    if not service:
        return
    try:
        draft_id = service.save_runtime_state(
            st.session_state.get("fa_draft_id"),
            industry=st.session_state.get("fa_industry"),
            function=st.session_state.get("fa_function"),
            position=st.session_state.get("fa_position"),
            current_step=current_step,
            current_section=current_section,
            section_data=st.session_state.get("fa_section_data", {}),
            section_messages=st.session_state.get("fa_section_messages", {}),
            section_done=st.session_state.get("fa_section_done", []),
            section_skipped=st.session_state.get("fa_section_skipped", []),
            generation_state=st.session_state.get("fa_generation_state", {}),
            status=status,
            last_error=last_error,
        )
        st.session_state.fa_draft_id = draft_id
    except Exception as exc:
        logger.warning(f"Flow A draft save skipped: {exc}")


# Auth UI
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Common navigation
# ---------------------------------------------------------------------------


def render_top_nav() -> None:
    left, spacer, resume_col, jd_col, home_col, logout_col = st.columns([3, 4, 1, 1, 1, 1])
    with left:
        st.markdown('<div class="topnav-title">JobHunter</div>', unsafe_allow_html=True)
    with resume_col:
        if st.button("我的简历", key="nav_resume", use_container_width=True):
            st.session_state.app_route = "resume_library"
            st.rerun()
    with jd_col:
        if st.button("JD库", use_container_width=True):
            st.session_state.app_route = "jd_library"
            st.rerun()
    with home_col:
        if st.button("首页", use_container_width=True):
            st.session_state.app_route = "landing"
            st.rerun()
    with logout_col:
        display = st.session_state.get("user_display_name") or "用户"
        if st.button(f"退出({display[:6]})", key="nav_logout", use_container_width=True):
            logout_user()
            st.rerun()
    # PR4 (M11): 数据活水面 — 仅在非 landing 路由，避免和 hero 重复
    if st.session_state.get("app_route") and st.session_state.app_route != "landing":
        _render_topnav_live_panel()
    st.markdown('<hr class="topnav-divider">', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Landing / mode select
# ---------------------------------------------------------------------------


def _render_topnav_live_panel() -> None:
    """4 个紧凑数字：全库 / 本周新增 / 行业 / 平台。每次刷新算一次（亚秒，cached 60s）。"""
    db = st.session_state.get("db")
    if not db:
        return
    try:
        snap = _compute_live_data_snapshot()
    except Exception:
        snap = {"total": 0, "new_week": 0, "industries": 0, "platforms": 0}
    c1, c2, c3, c4 = st.columns(4)
    metrics = [
        ("全库 JD", snap["total"], "所有未被删除的 JD"),
        ("本周新增", f"+{snap['new_week']}", "近 7 天新增的 JD"),
        ("行业覆盖", snap["industries"], "已分类的行业去重数"),
        ("来源平台", snap["platforms"], "JD 的 platform 字段去重数"),
    ]
    for col, (label, num, tip) in zip([c1, c2, c3, c4], metrics):
        with col:
            st.markdown(
                f'<div class="topnav-metric" title="{tip}">'
                f'<div class="topnav-metric-num">{num}</div>'
                f'<div class="topnav-metric-label">{label}</div></div>',
                unsafe_allow_html=True,
            )


@st.cache_data(ttl=60, show_spinner=False)
def _compute_live_data_snapshot(_db_marker: str = "default") -> Dict[str, int]:
    """活水面板数据源：cache 60s，避免每次 streamlit rerun 都跑 SQL。

    _db_marker 仅用于让 cache_data 在不同 db 间切换（测试 / 不同环境）。
    生产路径固定为 'default' → get_db()。"""
    from database.factory import get_db
    db = get_db()
    return _live_snapshot_from_db(db)


def _live_snapshot_from_db(db: Any) -> Dict[str, int]:
    """纯函数：从 db 拉 4 个数字。测试时直接传 tmp_db；上层 cache 包了它。"""
    conn = db._get_conn()
    try:
        total = int(conn.execute(
            "SELECT COUNT(*) FROM jds WHERE deleted_at IS NULL"
        ).fetchone()[0])
        new_week = int(conn.execute(
            "SELECT COUNT(*) FROM jds WHERE deleted_at IS NULL "
            "AND crawled_at >= datetime('now', '-7 days')"
        ).fetchone()[0])
        industries = int(conn.execute(
            "SELECT COUNT(DISTINCT industry_tag) FROM jds "
            "WHERE deleted_at IS NULL AND industry_tag IS NOT NULL"
        ).fetchone()[0])
        platforms = int(conn.execute(
            "SELECT COUNT(DISTINCT platform) FROM jds "
            "WHERE deleted_at IS NULL AND platform IS NOT NULL"
        ).fetchone()[0])
        return {
            "total": total,
            "new_week": new_week,
            "industries": industries,
            "platforms": platforms,
        }
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _render_landing_live_band() -> None:
    """Landing 末尾追加活水数据带，让新用户感受"数据是活的"。"""
    db = st.session_state.get("db")
    if not db:
        return
    try:
        snap = _compute_live_data_snapshot()
    except Exception:
        snap = {"total": 0, "new_week": 0, "industries": 0, "platforms": 0}

    st.markdown(
        '<div class="landing-live-band">'
        '<div class="landing-live-band-title">实时数据底子（来自 JD 库）</div>'
        "</div>",
        unsafe_allow_html=True,
    )
    c1, c2, c3, c4 = st.columns(4)
    metrics = [
        ("真实 JD 数量", f"{snap['total']:,}", "未被软删除"),
        ("本周新增", f"+{snap['new_week']}", "近 7 天 crawled_at"),
        ("覆盖行业", f"{snap['industries']}", "已分类行业去重"),
        ("来源平台", f"{snap['platforms']}", "51job / JobsDB / Liepin 等"),
    ]
    for col, (label, num, help_text) in zip([c1, c2, c3, c4], metrics):
        with col:
            st.metric(label=label, value=num, help=help_text)


def render_landing() -> None:
    import re

    page = st.query_params.get("page")
    if page in {"privacy", "terms"}:
        page_path = PROJECT_ROOT / f"{page}.html"
        if not page_path.exists():
            st.error(f"{page}.html 缺失，请检查项目根目录。")
            return
        html = page_path.read_text(encoding="utf-8")
        style_match = re.search(r"<style>(.*?)</style>", html, re.DOTALL)
        body_match = re.search(r"<body>(.*?)</body>", html, re.DOTALL)
        style = style_match.group(1) if style_match else ""
        body = body_match.group(1) if body_match else ""
        hide_chrome = """
div[data-testid="stSidebar"],
div[data-testid="stSidebarCollapsedControl"],
header[data-testid="stHeader"],
div[data-testid="stToolbar"],
div[data-testid="stDecoration"] {
    display: none !important;
}
section[data-testid="stMain"] {
    padding: 0 !important;
}
section[data-testid="stMain"] > div,
section[data-testid="stMain"] > div > div {
    padding: 0 !important;
    max-width: 100% !important;
}
"""
        st.html("<style>" + style + "\n" + hide_chrome + "</style>" + body)
        return

    route = st.query_params.get("route")
    if route in {"mode_select", "flow_a", "flow_b", "jd_library"}:
        st.session_state.app_route = route
        st.query_params.pop("route", None)
        st.rerun()
        return

    landing_path = PROJECT_ROOT / "landing.html"
    if not landing_path.exists():
        st.error("landing.html 缺失，请检查项目根目录。")
        return

    html = landing_path.read_text(encoding="utf-8")
    style_match = re.search(r"<style>(.*?)</style>", html, re.DOTALL)
    body_match = re.search(r"<body>(.*?)</body>", html, re.DOTALL)
    style = style_match.group(1) if style_match else ""
    body = body_match.group(1) if body_match else ""

    hide_chrome = """
div[data-testid="stSidebar"],
div[data-testid="stSidebarCollapsedControl"],
header[data-testid="stHeader"],
div[data-testid="stToolbar"],
div[data-testid="stDecoration"] {
    display: none !important;
}
section[data-testid="stMain"] {
    padding: 0 !important;
}
section[data-testid="stMain"] > div,
section[data-testid="stMain"] > div > div {
    padding: 0 !important;
    max-width: 100% !important;
}
"""

    st.html("<style>" + style + "\n" + hide_chrome + "</style>" + body)
    # PR4 (M11): landing hero 之下追加活水数据带（live numbers）
    _render_landing_live_band()


def render_mode_select() -> None:
    render_top_nav()
    st.markdown("## 你今天想做什么？")

    col_a, col_b = st.columns(2, gap="large")
    with col_a:
        with st.container(border=True):
            st.markdown("### 从0生成简历")
            st.write("适合没有现成简历，或想按目标岗位重新组织经历的人。")
            st.markdown("- 选择行业 / 职能 / 岗位\n- 和 Agent 多轮对话采集经历\n- 基于 JD 库生成岗位化简历")
            if st.button("开始生成", type="primary", use_container_width=True):
                st.session_state.app_route = "flow_a"
                st.rerun()

    with col_b:
        with st.container(border=True):
            st.markdown("### 修改已有简历")
            st.write("适合已有简历，需要针对某个 JD 做匹配分析和定制改写。")
            st.markdown("- 上传简历和 JD\n- 分析匹配度与差距\n- 生成优化简历和 Cover Letter")
            if st.button("开始优化", type="primary", use_container_width=True):
                reset_flow_b_state()
                st.session_state.app_route = "flow_b"
                st.rerun()


def _sync_flow_a_position_from_jd() -> None:
    """把 fa_jd_structured 同步到兼容旧逻辑的 fa_position / fa_industry / fa_function。

    旧 flow_a 后续步骤会读 fa_position；新 v3 步骤直接读 fa_jd_structured。
    """
    jd = st.session_state.get("fa_jd_structured") or {}
    if jd:
        st.session_state.fa_position = jd.get("title") or st.session_state.get("fa_position")
        st.session_state.fa_industry = (
            jd.get("industry") or st.session_state.get("fa_jd_industry")
            or st.session_state.get("fa_industry")
        )
        st.session_state.fa_function = (
            jd.get("function") or st.session_state.get("fa_jd_function")
            or st.session_state.get("fa_function")
        )


def render_flow_a() -> None:
    """v3 5-step state machine 分发：跳到对应 page 文件。"""
    _sync_flow_a_position_from_jd()
    fa_step = st.session_state.get("fa_step", 1)
    if fa_step == 1:
        st.switch_page("pages/03_📝_Flow_A_Step1.py")
    elif fa_step == 2:
        st.switch_page("pages/04_📝_Flow_A_Step2.py")
    else:  # fa_step in {3, 4, 5} — 同一个 page 内分发
        st.switch_page("pages/05_💬_Flow_A_Step3.py")


# ---------------------------------------------------------------------------
# Flow B
# ---------------------------------------------------------------------------


def render_flow_b() -> None:
    """业务页（Flow B）已迁到 pages/06_📄_Flow_B.py — 本函数仅留作路由入口。"""
    st.switch_page("pages/06_📄_Flow_B.py")


# ---------------------------------------------------------------------------
# JD library
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

def render_jd_library() -> None:
    """业务页（JD 库）已迁到 pages/07_📚_JD_Library.py — 本函数仅留作路由入口。"""
    st.switch_page("pages/07_📚_JD_Library.py")


def render_resume_library() -> None:
    """业务页（我的简历 / 投递历史）已迁到 pages/08_📈_Application_History.py。"""
    st.switch_page("pages/08_📈_Application_History.py")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


init_session_state()
init_app_services()

# v4 T1.1 登录门：landing（含 privacy/terms）公开，其余路由必须登录
if st.session_state.app_route != "landing" and not st.session_state.get("user_id"):
    render_auth_page()
elif st.session_state.app_route == "landing":
    render_landing()
elif st.session_state.app_route == "flow_a":
    render_flow_a()
elif st.session_state.app_route == "flow_b":
    render_flow_b()
elif st.session_state.app_route == "jd_library":
    render_jd_library()
elif st.session_state.app_route == "resume_library":
    render_resume_library()
else:
    st.session_state.app_route = "mode_select"
    render_mode_select()
