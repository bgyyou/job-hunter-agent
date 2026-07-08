#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Job Hunter product UI (Streamlit)."""
from __future__ import annotations

import asyncio
import os
import queue
import sys
import threading
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

from agents.coordinator import CoordinatorAgent
from agents.resume_flow_a import ResumeFlowA, SECTIONS
from config.settings import settings
from database.backends.sqlite_backend import SqliteBackend
from database.classifier import Classifier
from services.audit_service import log_action
from services.flow_a_draft_service import (
    FlowADraftService,
    missing_fields_label,
    validate_section_completion,
)
from services.jd_library_service import (
    JdLibraryError,
    cleanup_garbage_public_jds,
    count_visible_jds,
    delete_user_jd,
    ensure_public_seed_jds,
    get_visible_jd,
    insert_user_jd,
    list_sources,
    list_visible_jds,
)
from services.resume_library_service import (
    ResumeLibraryError,
    clone_resume,
    get_primary_resume,
    list_resume_versions,
    set_primary_resume,
)
from services.pdf_ingestion_service import PdfIngestionService
from tools import taxonomy
from tools.generator.cover_letter_generator import CoverLetterGenerator
from tools.generator.resume_generator import ResumeGenerator
from tools.generator.resume_optimizer import ResumeOptimizer
from tools.generator.resume_pdf import html_to_pdf_safe
from tools.jd_indexer import embed_and_store_jd_chunks
from tools.llm import OpenAICompatibleClient
from tools.resume_parser import ResumeParser
from tools.scraper.jd_analyzer_enhanced import JDAnalyzerEnhanced

settings.setup_logging()

LLM_COLLECT_SECTION_KEYS = {"experience", "projects"}

# 登录系统后期再加，当前用固定 user_id 写库
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


def split_items(text: str) -> List[str]:
    if not text:
        return []
    normalized = text.replace("，", ",").replace("；", ";").replace("\n", ",")
    parts: List[str] = []
    for chunk in normalized.replace(";", ",").split(","):
        item = chunk.strip()
        if item:
            parts.append(item)
    return parts


def parse_languages(text: str) -> List[Dict[str, str]]:
    languages = []
    for item in split_items(text):
        if "(" in item and item.endswith(")"):
            name, level = item[:-1].split("(", 1)
        elif "（" in item and item.endswith("）"):
            name, level = item[:-1].split("（", 1)
        else:
            name, level = item, ""
        if name.strip():
            languages.append({"name": name.strip(), "level": level.strip()})
    return languages


# ---------------------------------------------------------------------------
# Session / services
# ---------------------------------------------------------------------------


def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def stream_llm_to_sync(async_gen):
    """把 async generator 转成 sync generator，用线程跑 async，queue 传 chunk。

    LLM client 的 analyze_stream 是 async generator，但 Streamlit 主线程是同步的。
    用 daemon 线程跑 async generator，chunk 通过 queue 传到主线程，st.write_stream
    能逐 chunk 实时渲染。
    """
    q: "queue.Queue[Any]" = queue.Queue()
    SENTINEL = object()

    def runner():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def _drain():
                async for chunk in async_gen:
                    q.put(chunk)
            loop.run_until_complete(_drain())
        except Exception as exc:
            q.put(exc)
        finally:
            q.put(SENTINEL)
            loop.close()

    threading.Thread(target=runner, daemon=True).start()

    while True:
        item = q.get()
        if item is SENTINEL:
            break
        if isinstance(item, Exception):
            raise item
        yield item


def init_session_state() -> None:
    defaults = {
        "app_route": "landing",
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
        st.session_state.db = SqliteBackend(db_path=settings.db_path)
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
        )
        st.session_state.llm_client = llm_client
        st.session_state.agent = CoordinatorAgent(llm_client=llm_client)
        st.session_state.services_ready = True
        st.session_state.llm_init_error = None
    except Exception as exc:
        st.session_state.services_ready = False
        st.session_state.llm_init_error = f"AI 服务初始化失败：{exc}"


def current_user_id() -> str:
    return ANONYMOUS_USER_ID


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


def reset_flow_b_state() -> None:
    for key in [
        "resume_data", "resume_id", "jd_result", "jd_id", "match_result",
        "last_match_id", "last_match_score", "optimized_resume",
        "optimized_resume_html", "cover_letter",
    ]:
        st.session_state[key] = None
    st.session_state.last_opt_ids = []
    st.session_state.flow_b_step = "resume"


def _flow_a_collect_sections() -> List[Dict[str, Any]]:
    return [s for s in SECTIONS if not s.get("derived") and s["key"] in LLM_COLLECT_SECTION_KEYS]


def _flow_a_draft_service() -> Optional[FlowADraftService]:
    db = st.session_state.get("db")
    if not db:
        return None
    return FlowADraftService(db, current_user_id())


def _invalidate_flow_a_generation() -> None:
    for key in ["fa_resume_data", "fa_resume_md", "fa_resume_html", "fa_resume_pdf", "fa_skeleton"]:
        st.session_state[key] = None
    st.session_state.fa_generation_state = {}
    st.session_state.fa_pdf_status = None
    st.session_state.fa_pdf_error = None


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


def _restore_flow_a_draft(draft: Dict[str, Any]) -> None:
    collect_sections = _flow_a_collect_sections()
    collect_keys = [s["key"] for s in collect_sections]
    section_status = draft.get("section_status") or {}
    done = [k for k, v in section_status.items() if v == "done"]
    skipped = [k for k, v in section_status.items() if v == "skipped"]
    current_section = draft.get("current_section")

    st.session_state.fa_draft_id = draft.get("id")
    st.session_state.fa_industry = draft.get("industry")
    st.session_state.fa_function = draft.get("function")
    st.session_state.fa_position = draft.get("position")
    st.session_state.fa_section_data = draft.get("section_data") or {}
    st.session_state.fa_section_messages = draft.get("section_messages") or {}
    st.session_state.fa_section_done = done
    st.session_state.fa_section_skipped = skipped
    st.session_state.fa_generation_state = draft.get("generation_state") or {}
    st.session_state.fa_last_error = draft.get("last_error")
    st.session_state.fa_basic_form_done = bool(st.session_state.fa_section_data.get("header"))

    if draft.get("current_step") in {"generate", "completed"}:
        st.session_state.fa_section_index = len(collect_sections)
    elif current_section in collect_keys:
        st.session_state.fa_section_index = collect_keys.index(current_section)
    else:
        st.session_state.fa_section_index = 0
        for idx, key in enumerate(collect_keys):
            if key not in done and key not in skipped:
                st.session_state.fa_section_index = idx
                break


def _render_flow_a_recovery_prompt() -> bool:
    if st.session_state.get("fa_draft_id") or st.session_state.get("fa_position"):
        return False
    service = _flow_a_draft_service()
    if not service:
        return False
    draft = service.get_latest_recoverable_draft()
    if not draft:
        return False

    st.info(
        f"检测到上次未完成的简历草稿：{draft.get('industry') or '-'} / "
        f"{draft.get('position') or '-'}。可以直接恢复，不用从头来。"
    )
    c1, c2, _ = st.columns([1, 1, 4])
    with c1:
        if st.button("恢复上次进度", type="primary"):
            _restore_flow_a_draft(draft)
            st.rerun()
    with c2:
        if st.button("放弃草稿，重新开始"):
            service.abandon_draft(draft["id"])
            st.rerun()
    return True


def _advance_flow_a_section(section_key: str, *, skipped: bool = False) -> None:
    if skipped:
        if section_key not in st.session_state.fa_section_skipped:
            st.session_state.fa_section_skipped.append(section_key)
        if section_key in st.session_state.fa_section_done:
            st.session_state.fa_section_done.remove(section_key)
    else:
        if section_key not in st.session_state.fa_section_done:
            st.session_state.fa_section_done.append(section_key)
        if section_key in st.session_state.fa_section_skipped:
            st.session_state.fa_section_skipped.remove(section_key)
    st.session_state.fa_incomplete_confirm_section = None
    st.session_state.fa_incomplete_missing = []
    st.session_state.fa_section_index += 1
    _invalidate_flow_a_generation()
    next_sections = _flow_a_collect_sections()
    next_section = None
    if st.session_state.fa_section_index < len(next_sections):
        next_section = next_sections[st.session_state.fa_section_index]["key"]
    _save_flow_a_draft(
        "collect" if next_section else "generate",
        next_section,
    )


def _apply_flow_a_section_extracted(
    section_key: str,
    extracted: Any,
    *,
    allow_incomplete: bool = False,
) -> bool:
    st.session_state.fa_section_data[section_key] = extracted
    validation = validate_section_completion(section_key, extracted)
    if validation.complete or allow_incomplete:
        _advance_flow_a_section(section_key)
        return True

    st.session_state.fa_incomplete_confirm_section = section_key
    st.session_state.fa_incomplete_missing = validation.missing_fields
    _save_flow_a_draft("collect", section_key)
    return False


# ---------------------------------------------------------------------------
# Auth UI
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Common navigation
# ---------------------------------------------------------------------------


def render_top_nav() -> None:
    left, spacer, resume_col, jd_col, home_col = st.columns([3, 5, 1, 1, 1])
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


# ---------------------------------------------------------------------------
# Flow A
# ---------------------------------------------------------------------------


def render_flow_a() -> None:
    render_top_nav()
    st.header("从0生成简历")
    st.caption("先确定目标岗位，再按 section 逐步采集信息。")

    if not require_services():
        return

    flow_a = ResumeFlowA(st.session_state.llm_client, db=st.session_state.db)

    if _render_flow_a_recovery_prompt():
        return

    collect_sections = _flow_a_collect_sections()
    total_sections = 1 + len(collect_sections)

    if not st.session_state.fa_position:
        st.markdown('<span class="step-pill">第 1 步</span>选择目标岗位', unsafe_allow_html=True)
        col_i, col_f, col_p = st.columns(3)
        with col_i:
            industries = taxonomy.list_industries()
            industry = st.selectbox("行业", ["(请选择)"] + industries, key="fa_industry_select")
        with col_f:
            functions = taxonomy.list_functions(industry) if industry != "(请选择)" else []
            function = st.selectbox("职能", ["(请选择)"] + functions if functions else ["(请先选行业)"], key="fa_function_select", disabled=not functions)
        with col_p:
            positions = taxonomy.list_positions(industry, function) if industry != "(请选择)" and function and function != "(请选择)" else []
            position = st.selectbox("岗位", ["(请选择)"] + positions if positions else ["(请先选职能)"], key="fa_position_select", disabled=not positions)

        if st.button("确定，填写基础信息", type="primary", disabled=position == "(请选择)" or not positions):
            st.session_state.fa_industry = industry
            st.session_state.fa_function = function
            st.session_state.fa_position = position
            st.session_state.fa_section_index = 0
            st.session_state.fa_section_data = {}
            st.session_state.fa_section_messages = {}
            st.session_state.fa_section_done = []
            st.session_state.fa_section_skipped = []
            st.session_state.fa_basic_form_done = False
            _save_flow_a_draft("basic_form", None)
            st.rerun()
        return

    if not st.session_state.fa_basic_form_done:
        st.progress(0.0, text=f"进度 0/{total_sections}")
        st.markdown('<span class="step-pill">第 2 步</span>填写基础信息', unsafe_allow_html=True)
        st.caption("这些结构化字段不调用 LLM，直接进入简历。")
        if st.button("重新选择岗位"):
            reset_flow_a_state()
            st.rerun()

        with st.form("flow_a_basic_form"):
            st.markdown("#### 个人信息")
            c1, c2, c3 = st.columns(3)
            with c1:
                name = st.text_input("姓名 *")
                phone = st.text_input("电话")
            with c2:
                email = st.text_input("邮箱")
                wechat = st.text_input("微信（可选）")
            with c3:
                linkedin = st.text_input("LinkedIn / 作品链接（可选）")
                location = st.text_input("所在地（可选）")

            st.markdown("#### 教育经历")
            e1, e2, e3 = st.columns(3)
            with e1:
                school = st.text_input("学校 *")
                degree = st.text_input("学历 *", placeholder="本科 / 硕士 / 博士")
            with e2:
                major = st.text_input("专业 *")
                start_year = st.text_input("入学年份", placeholder="2020")
            with e3:
                end_year = st.text_input("毕业年份", placeholder="2024")

            st.markdown("#### 技能与优势")
            skills_text = st.text_area("技能（用逗号或换行分隔）", placeholder="Python, SQL, LLM, RAG, 产品设计")
            languages_text = st.text_input("语言能力（用逗号分隔）", placeholder="中文（母语）, 英语（CET-6）")
            raw_advantages = st.text_area("个人优势 / 亮点素材", placeholder="例如：跨团队推进强、做过 0-1 AI 产品、有数据分析背景……")
            submitted = st.form_submit_button("保存基础信息，开始经历对话", type="primary")

        if submitted:
            if not name.strip() or not school.strip() or not degree.strip() or not major.strip():
                st.error("姓名、学校、学历、专业为必填。")
            elif not phone.strip() and not email.strip():
                st.error("电话和邮箱至少填写一项。")
            else:
                st.session_state.fa_section_data.update({
                    "header": {
                        "name": name.strip(),
                        "contact": {
                            "phone": phone.strip(),
                            "email": email.strip(),
                            "wechat": wechat.strip(),
                            "linkedin": linkedin.strip(),
                        },
                        "location": location.strip(),
                    },
                    "education": [{
                        "school": school.strip(),
                        "degree": degree.strip(),
                        "major": major.strip(),
                        "start_year": start_year.strip(),
                        "end_year": end_year.strip(),
                    }],
                    "skills": split_items(skills_text),
                    "languages": parse_languages(languages_text),
                    "raw_advantages": raw_advantages.strip(),
                })
                st.session_state.fa_basic_form_done = True
                first_section = collect_sections[0]["key"] if collect_sections else None
                _save_flow_a_draft("collect" if first_section else "generate", first_section)
                st.rerun()
        return

    if st.session_state.fa_section_index < len(collect_sections):
        section = collect_sections[st.session_state.fa_section_index]
        section_key = section["key"]
        finished = 1 + len(st.session_state.fa_section_done) + len(st.session_state.fa_section_skipped)
        st.progress(finished / total_sections, text=f"进度 {finished}/{total_sections}")
        st.markdown(f'<span class="step-pill">第 3 步</span>采集 {section["name"]}', unsafe_allow_html=True)
        st.caption(f"目标：{st.session_state.fa_industry} / {st.session_state.fa_position}")

        nav_back, nav_reset, _ = st.columns([1, 1, 4])
        with nav_back:
            if st.session_state.fa_section_index > 0 and st.button("← 返回上一节"):
                prev_section = collect_sections[st.session_state.fa_section_index - 1]["key"]
                st.session_state.fa_section_index -= 1
                if prev_section in st.session_state.fa_section_done:
                    st.session_state.fa_section_done.remove(prev_section)
                if prev_section in st.session_state.fa_section_skipped:
                    st.session_state.fa_section_skipped.remove(prev_section)
                st.session_state.fa_incomplete_confirm_section = None
                st.session_state.fa_incomplete_missing = []
                _invalidate_flow_a_generation()
                _save_flow_a_draft("collect", prev_section)
                st.rerun()
        with nav_reset:
            if st.button("重新选择岗位"):
                reset_flow_a_state()
                st.rerun()

        if st.session_state.get("fa_incomplete_confirm_section") == section_key:
            missing = st.session_state.get("fa_incomplete_missing", [])
            st.warning(
                "本节还没收齐：" + missing_fields_label(missing)
                + "。继续补充，或者确认信息不全也进入下一节。"
            )
            if st.button("确认信息不全也继续", key=f"fa_force_continue_{section_key}"):
                _apply_flow_a_section_extracted(
                    section_key,
                    st.session_state.fa_section_data.get(section_key) or ResumeFlowA._empty_section_value(section_key),
                    allow_incomplete=True,
                )
                st.rerun()

        # PR5 (M12): 模式切换 — 粘贴通道 / 逐段对话 二选一
        extract_mode = st.radio(
            "采集方式",
            ["🪄 粘贴完整文本（推荐，10 秒）", "💬 逐段对话"],
            horizontal=True,
            key="fa_extract_mode_radio",
        )
        is_paste_mode = "粘贴" in extract_mode

        if is_paste_mode:
            _render_flow_a_paste_panel(flow_a)
            return

        sec_msgs = st.session_state.fa_section_messages.setdefault(section_key, [])
        for msg in sec_msgs:
            with st.chat_message("user" if msg["role"] == "user" else "assistant"):
                st.markdown(msg["content"])

        needs_assistant_turn = not sec_msgs or sec_msgs[-1]["role"] == "user"
        if needs_assistant_turn:
            try:
                msgs_for_llm = sec_msgs if sec_msgs else [{"role": "user", "content": f"开始采集{section['name']}吧。"}]
                llm_messages, force_close, rounds_used = flow_a._build_chat_messages(
                    section_key=section_key,
                    messages=msgs_for_llm,
                    collected_so_far=st.session_state.fa_section_data,
                    industry=st.session_state.fa_industry,
                    position=st.session_state.fa_position,
                )
                async_gen = st.session_state.llm_client.analyze_stream(
                    messages=llm_messages, max_tokens=600, temperature=0.6,
                )
                content_gen = (chunk.content for chunk in stream_llm_to_sync(async_gen) if chunk.content)
                with st.chat_message("assistant"):
                    full_text = st.write_stream(content_gen)

                reply = ResumeFlowA._parse_chat_reply(full_text, force_close, rounds_used)
                if not sec_msgs:
                    sec_msgs.append({"role": "user", "content": f"开始采集{section['name']}吧。"})
                sec_msgs.append({"role": "assistant", "content": reply["message"]})

                if reply["type"] == "section_skipped":
                    _advance_flow_a_section(section_key, skipped=True)
                elif reply["type"] == "section_done":
                    extracted = run_async(flow_a.extract_section(section_key, sec_msgs))
                    _apply_flow_a_section_extracted(section_key, extracted)
                else:
                    _save_flow_a_draft("collect", section_key)
                st.rerun()
            except Exception as exc:
                st.session_state.fa_last_error = str(exc)
                _save_flow_a_draft("collect", section_key, last_error=str(exc))
                st.error(f"AI 响应失败：{exc}")
                if st.button("重试这条 AI 响应", key=f"fa_retry_ai_{section_key}_{len(sec_msgs)}"):
                    st.rerun()

        user_input = st.chat_input(f"回复关于「{section['name']}」的问题...")
        if user_input:
            sec_msgs.append({"role": "user", "content": user_input})
            st.session_state.fa_incomplete_confirm_section = None
            st.session_state.fa_incomplete_missing = []
            _save_flow_a_draft("collect", section_key)
            st.rerun()

        b1, b2, _ = st.columns(3)
        with b1:
            if section.get("skippable") and st.button(f"跳过 {section['name']}"):
                _advance_flow_a_section(section_key, skipped=True)
                st.rerun()
        with b2:
            if st.button("完成本节，进入下一节"):
                try:
                    extracted = run_async(flow_a.extract_section(section_key, sec_msgs)) if sec_msgs else ResumeFlowA._empty_section_value(section_key)
                    _apply_flow_a_section_extracted(section_key, extracted)
                except Exception as exc:
                    st.session_state.fa_last_error = str(exc)
                    _save_flow_a_draft("collect", section_key, last_error=str(exc))
                    st.warning(f"提取本节数据时出错：{exc}。状态已保存，可以重试。")
                st.rerun()
        return

    st.progress(1.0, text=f"进度 {total_sections}/{total_sections} ✓")
    st.markdown('<span class="step-pill">第 4 步</span>生成简历', unsafe_allow_html=True)
    back_col, reset_col, _ = st.columns([1, 1, 4])
    with back_col:
        if collect_sections and st.button("← 返回上一节修改"):
            prev_section = collect_sections[-1]["key"]
            st.session_state.fa_section_index = len(collect_sections) - 1
            if prev_section in st.session_state.fa_section_done:
                st.session_state.fa_section_done.remove(prev_section)
            if prev_section in st.session_state.fa_section_skipped:
                st.session_state.fa_section_skipped.remove(prev_section)
            st.session_state.fa_incomplete_confirm_section = None
            st.session_state.fa_incomplete_missing = []
            _invalidate_flow_a_generation()
            _save_flow_a_draft("collect", prev_section)
            st.rerun()
    with reset_col:
        if st.button("重新选择岗位"):
            reset_flow_a_state()
            st.rerun()
    if st.session_state.fa_resume_md is None:
        with st.status("正在生成简历...", expanded=True) as status:
            try:
                # v2.1 P2-1 阶段一：流式占位 — 用户能看到 LLM 在动
                skeleton_placeholder = st.empty()
                derive_placeholder = st.empty()
                rewrite_status_placeholder = st.empty()
                rewrite_log: list[str] = []

                def _skeleton_cb(delta: str, accumulated: str) -> None:
                    """RAG skeleton 蒸馏进度 — 用户看到字一个个出来。"""
                    skeleton_placeholder.markdown(
                        f"**岗位核心要求提炼中**（基于 {st.session_state.fa_position} 相关 JD）"
                        f"\n\n```\n{accumulated}\n```"
                        f"\n\n_逐字输出中..._"
                    )

                def _derive_cb(delta: str, accumulated: str) -> None:
                    """派生 summary / core_competencies 进度。"""
                    derive_placeholder.markdown(
                        f"**个人总结 + 核心能力生成中**"
                        f"\n\n```json\n{accumulated}\n```"
                        f"\n\n_逐字输出中..._"
                    )

                def _rewrite_cb(stage: str, payload: dict) -> None:
                    label = "经历" if stage == "experience" else "项目"
                    rewrite_log.append(f"✅ 已改写 {payload.get('count', 0)} 段{label}")
                    rewrite_status_placeholder.markdown(
                        "\n\n".join(rewrite_log) if rewrite_log else "_改写进度:_"
                    )

                def _generation_state_cb(state: Dict[str, Any]) -> None:
                    st.session_state.fa_generation_state = dict(state)
                    _save_flow_a_draft("generate", None, status="generating")

                _save_flow_a_draft("generate", None, status="generating")
                status.update(label="1/5 检索 JD 库 + 提炼岗位核心要求（可恢复）...", state="running")
                payload = run_async(flow_a.generate_resume_payload_resumable(
                    collected=st.session_state.fa_section_data or {},
                    industry=st.session_state.fa_industry,
                    position=st.session_state.fa_position,
                    generation_state=st.session_state.get("fa_generation_state", {}),
                    state_callback=_generation_state_cb,
                    skeleton_callback=_skeleton_cb,
                    derive_callback=_derive_cb,
                    rewrite_callback=_rewrite_cb,
                ))
                st.session_state.fa_generation_state = payload.get("generation_state", st.session_state.get("fa_generation_state", {}))

                status.update(label="2/5 组装简历结构...", state="running")
                skeleton = payload["skeleton"]
                final_data = flow_a._normalize_resume_shape(payload["resume"])
                st.session_state.fa_resume_data = final_data
                st.session_state.fa_skeleton = skeleton
                st.session_state.fa_resume_md = flow_a.to_markdown(final_data)
                html_str = flow_a.to_html(final_data)
                st.session_state.fa_resume_html = html_str
                skeleton_placeholder.empty()
                derive_placeholder.empty()
                rewrite_status_placeholder.empty()

                status.update(label="3/5 启动 PDF 后台渲染（不阻塞预览）...", state="running")
                # PR6 (M12): PDF 改后台线程，先让用户看到 MD/HTML
                _kick_off_background_pdf(html_str)
                st.session_state.fa_generation_state["render"] = {"status": "done"}
                _save_flow_a_draft("completed", None, status="completed")

                status.update(label="4/5 完成！", state="complete")
                st.success("简历生成成功！")
            except Exception as exc:
                status.update(label="生成失败", state="error")
                st.session_state.fa_last_error = str(exc)
                _save_flow_a_draft("generate", None, status="failed", last_error=str(exc))
                st.error(f"生成失败：{exc}")
                if st.button("重试生成（保留已完成步骤）", key="fa_retry_generation"):
                    st.rerun()

    if st.session_state.fa_resume_md:
        # PR6 (M12): 先把后台线程结果同步进 session_state，让 rerun 后按钮 enable
        _poll_pdf_status()
        st.markdown(st.session_state.fa_resume_md)
        sk = st.session_state.fa_skeleton or {}
        # PR3 (M11): 改写依据 + 来源面板
        _render_flow_a_provenance_panel(sk)
        dl1, dl2, dl3, dl4, dl5 = st.columns(5)
        pdf_status = st.session_state.get("fa_pdf_status", "ready")
        pdf_disabled = pdf_status != "ready"
        pdf_help = None
        if pdf_status == "pending":
            pdf_help = "PDF 生成中（2-5 秒）…"
        elif pdf_status == "failed":
            pdf_help = f"PDF 生成失败：{st.session_state.get('fa_pdf_error')}"
        with dl1:
            st.download_button(
                "下载 PDF" if pdf_status == "ready" else "PDF 生成中…",
                st.session_state.fa_resume_pdf,
                file_name=f"{st.session_state.fa_position}_简历.pdf",
                mime="application/pdf",
                disabled=pdf_disabled,
                help=pdf_help,
            )
        with dl2:
            st.download_button("下载 Markdown", st.session_state.fa_resume_md, file_name=f"{st.session_state.fa_position}_简历.md", mime="text/markdown")
        with dl3:
            st.download_button("下载 HTML", st.session_state.fa_resume_html, file_name=f"{st.session_state.fa_position}_简历.html", mime="text/html")
        with dl4:
            if st.button("保存到数据库"):
                rd = st.session_state.fa_resume_data
                resume_payload = {
                    "user_id": current_user_id(),
                    "name": rd.get("header", {}).get("name", ""),
                    "phone": rd.get("header", {}).get("contact", {}).get("phone", ""),
                    "email": rd.get("header", {}).get("contact", {}).get("email", ""),
                    "summary": rd.get("summary", "") or rd.get("header", {}).get("summary", ""),
                    "skills": rd.get("skills", []),
                    "education": rd.get("education", []),
                    "projects": rd.get("projects", []),
                    "target_roles": [st.session_state.fa_position],
                }
                resume_id = st.session_state.db.insert_resume(resume_payload)
                log_action(
                    st.session_state.db,
                    user_id=current_user_id(),
                    action="resume.create",
                    target_table="resumes",
                    target_id=resume_id,
                    details={"flow": "a", "position": st.session_state.fa_position},
                )
                st.success(f"已保存，resume_id={resume_id[:12]}...")
        with dl5:
            if st.button("重新开始"):
                reset_flow_a_state()
                st.rerun()


# ---------------------------------------------------------------------------
# Flow B
# ---------------------------------------------------------------------------


def resume_to_db_payload(resume_data: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    header = resume_data.get("header", {})
    contact = header.get("contact", {})
    experience = resume_data.get("experience", [])
    # experience_years：从 experience 列表长度估算（保守，每个条目算 1 年）
    experience_years = max(len(experience), 0)
    return {
        "user_id": user_id,
        "name": header.get("name", resume_data.get("name", "")),
        "phone": contact.get("phone", resume_data.get("phone")),
        "email": contact.get("email", resume_data.get("email")),
        "summary": header.get("summary", resume_data.get("summary", "")),
        "skills": resume_data.get("skills", []),
        "education": resume_data.get("education", []),
        "projects": resume_data.get("projects", []),
        "experience": experience,
        "experience_years": experience_years,
    }


def _db_resume_to_resume_data(row: Dict[str, Any]) -> Dict[str, Any]:
    """把 DB 里存的 resume 行转回 ResumeParser 输出的 resume_data 格式。

    ResumeOptimizer / ResumeGenerator 读的是 header/experience/projects/
    skills/education/summary 这些字段。
    """
    header = {
        "name": row.get("name", ""),
        "summary": row.get("summary", ""),
        "contact": {
            "phone": row.get("phone", ""),
            "email": row.get("email", ""),
        },
    }
    return {
        "header": header,
        "summary": row.get("summary", ""),
        "experience": row.get("experience", []),
        "projects": row.get("projects", []),
        "skills": row.get("skills", []),
        "education": row.get("education", []),
        "languages": [],
        "core_competencies": [],
    }


def jd_to_db_payload(jd_text: str, jd_result: Dict[str, Any], user_id: str, source: str = "manual") -> Dict[str, Any]:
    clf = Classifier()
    tags = clf.classify(jd_result.get("title", ""), jd_text)
    return {
        "user_id": user_id,
        "url": f"manual://{abs(hash(jd_text))}",
        "title": jd_result.get("title", ""),
        "company": jd_result.get("company", ""),
        "location": jd_result.get("location", ""),
        "raw_text": jd_text,
        "source": source,
        "parsed_sections": {
            "requirements": jd_result.get("core_requirements", []),
            "preferred": jd_result.get("preferred_requirements", []),
            "implicit": jd_result.get("implicit_requirements", ""),
        },
        "tags": jd_result.get("keywords", []),
        "language": jd_result.get("language", "zh"),
        "industry_tag": tags.get("industry_tag"),
        "function_tag": tags.get("function_tag"),
        "position_tag": tags.get("position_tag"),
        "auto_classified": 1,
    }


def render_generation_toolbar() -> None:
    can_generate = bool(
        st.session_state.services_ready
        and st.session_state.resume_data
        and st.session_state.jd_result
        and st.session_state.match_result
    )
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        if st.button("生成优化简历", type="primary", disabled=not can_generate, use_container_width=True):
            generate_optimized_resume()
    with col2:
        if st.button("生成 Cover Letter", disabled=not can_generate, use_container_width=True):
            generate_cover_letter()
    with col3:
        if not can_generate:
            st.caption("完成上传简历、上传/选择 JD、匹配度分析后即可生成。")


def generate_optimized_resume() -> None:
    with st.spinner("正在基于 JD 库生成优化简历..."):
        try:
            from tools.retriever import Retriever
            jd_query = st.session_state.jd_result.get("title") or st.session_state.jd_result.get("raw_text", "")[:200]
            reference_chunks = Retriever().retrieve(jd_query, top_k=3, filter_chunk_type="responsibility")
            recommendations = st.session_state.match_result.get("recommendations", [])
            optimizer = ResumeOptimizer(st.session_state.llm_client)
            optimized = run_async(optimizer.optimize(
                st.session_state.resume_data,
                st.session_state.jd_result,
                recommendations,
                reference_chunks=reference_chunks,
            ))
            generator = ResumeGenerator()
            st.session_state.optimized_resume = generator.to_markdown(optimized)
            st.session_state.optimized_resume_html = generator.to_html(optimized)
            st.success("优化简历已生成。")
        except Exception as exc:
            st.error(f"生成优化简历失败：{exc}")


def generate_cover_letter() -> None:
    with st.spinner("正在生成 Cover Letter..."):
        try:
            company = st.session_state.flow_b_company_name or st.session_state.jd_result.get("company", "目标公司")
            generator = CoverLetterGenerator(st.session_state.llm_client)
            st.session_state.cover_letter = run_async(generator.generate(
                st.session_state.resume_data,
                st.session_state.jd_result,
                company,
            ))
            st.success("Cover Letter 已生成。")
        except Exception as exc:
            st.error(f"生成 Cover Letter 失败：{exc}")


def render_flow_b() -> None:
    render_top_nav()
    st.header("修改已有简历")
    st.caption("上传简历和目标 JD，先看匹配度，再生成优化简历和 Cover Letter。")

    if not require_services():
        return

    st.divider()

    step1, step2, step3 = st.columns(3)
    step1.markdown('<span class="step-pill">1 上传简历</span>', unsafe_allow_html=True)
    step2.markdown('<span class="step-pill">2 上传 / 选择 JD</span>', unsafe_allow_html=True)
    step3.markdown('<span class="step-pill">3 匹配分析</span>', unsafe_allow_html=True)

    with st.expander("1. 上传并解析简历", expanded=st.session_state.resume_data is None):
        uploaded_resume = st.file_uploader("上传简历文件", type=["pdf", "docx", "md", "txt"], key="fb_resume_upload")
        if uploaded_resume and st.button("解析简历", type="primary"):
            temp_dir = PROJECT_ROOT / "data" / "temp"
            temp_dir.mkdir(parents=True, exist_ok=True)
            temp_path = temp_dir / uploaded_resume.name
            temp_path.write_bytes(uploaded_resume.getbuffer())
            with st.spinner("正在解析简历..."):
                parser = ResumeParser(llm_client=st.session_state.llm_client)
                resume_data = run_async(parser.parse(str(temp_path)))
                st.session_state.resume_data = resume_data
                st.session_state.resume_id = st.session_state.db.insert_resume(
                    resume_to_db_payload(resume_data, current_user_id())
                )
                log_action(
                    st.session_state.db,
                    user_id=current_user_id(),
                    action="resume.create",
                    target_table="resumes",
                    target_id=st.session_state.resume_id,
                    details={"flow": "b", "source": uploaded_resume.name},
                )
                st.success("简历解析完成。")
        if st.session_state.resume_data:
            st.json(st.session_state.resume_data, expanded=False)

        with st.expander("从简历库选择"):
            from services.resume_library_service import list_resumes_flat
            saved = list_resumes_flat(st.session_state.db, current_user_id())
            if not saved:
                st.info("简历库为空，请先上传并保存简历。")
            else:
                opts = {f"{r['name']}（v{r.get('version',1)}·{r.get('updated_at','')[:10]}）": r["id"] for r in saved}
                selected_label = st.selectbox("选择简历版本", list(opts.keys()), key="fb_lib_resume_sel")
                if selected_label and st.button("加载到当前会话", key="fb_load_lib_resume"):
                    rid = opts[selected_label]
                    row = st.session_state.db.get_resume(rid)
                    if row:
                        st.session_state.resume_data = _db_resume_to_resume_data(row)
                        st.session_state.resume_id = rid
                        st.rerun()
                st.caption("注意：从库加载会覆盖当前会话中的简历内容。")

    with st.expander("2. 上传 / 选择目标 JD", expanded=st.session_state.resume_data is not None and st.session_state.jd_result is None):
        input_type = st.radio("JD 来源", ["粘贴 JD", "上传 PDF", "从 JD库选择", "职位 URL"], horizontal=True, key="fb_jd_input_type_radio")
        if input_type == "粘贴 JD":
            jd_text = st.text_area("粘贴目标 JD", height=220)
            if st.button("分析并保存 JD", disabled=not jd_text):
                with st.spinner("正在分析 JD..."):
                    analyzer = JDAnalyzerEnhanced(llm_client=st.session_state.llm_client)
                    jd_result = run_async(analyzer.parse_from_text(jd_text))
                    jd_payload = jd_to_db_payload(jd_text, jd_result, current_user_id(), source="manual")
                    jd_id = insert_user_jd(st.session_state.db, current_user_id(), jd_payload)
                    embed_and_store_jd_chunks(st.session_state.db, jd_id, jd_text, user_id=current_user_id())
                    log_action(
                        st.session_state.db,
                        user_id=current_user_id(),
                        action="jd.create",
                        target_table="jds",
                        target_id=jd_id,
                        details={"flow": "b", "source": "manual"},
                    )
                    st.session_state.jd_result = jd_result
                    st.session_state.jd_id = jd_id
                    st.success("JD 已分析并保存到 JD库。")
        elif input_type == "上传 PDF":
            uploaded_pdf = st.file_uploader("上传 JD PDF", type=["pdf"], key="fb_jd_pdf")
            if uploaded_pdf and st.button("解析 PDF JD"):
                upload_dir = PROJECT_ROOT / "data" / "uploads"
                upload_dir.mkdir(parents=True, exist_ok=True)
                pdf_path = upload_dir / uploaded_pdf.name
                pdf_path.write_bytes(uploaded_pdf.getbuffer())
                with st.spinner("正在解析 PDF JD..."):
                    jd_id = PdfIngestionService(db=st.session_state.db, classifier=Classifier()).ingest(
                        str(pdf_path), user_id=current_user_id(),
                    )
                    log_action(
                        st.session_state.db,
                        user_id=current_user_id(),
                        action="jd.create",
                        target_table="jds",
                        target_id=jd_id,
                        details={"flow": "b", "source": "pdf", "file": uploaded_pdf.name},
                    )
                    jd = st.session_state.db.get_jd(jd_id)
                    st.session_state.jd_id = jd_id
                    st.session_state.jd_result = {
                        "title": jd.get("title", ""),
                        "company": jd.get("company", ""),
                        "location": jd.get("location", ""),
                        "core_requirements": jd.get("parsed_sections", {}).get("requirements", []),
                        "keywords": jd.get("tags", []),
                        "raw_text": jd.get("raw_text", ""),
                    }
                    st.success("PDF JD 已入库。")
        elif input_type == "从 JD库选择":
            jd_search = st.text_input("搜索 JD库", placeholder="职位、公司、关键词", key="flow_b_jd_search")
            total = count_visible_jds(st.session_state.db, current_user_id(), search=jd_search or None)
            page_size = st.session_state.flow_b_jd_page_size
            max_page = max(1, (total + page_size - 1) // page_size)
            st.session_state.flow_b_jd_page = min(st.session_state.flow_b_jd_page, max_page)
            p1, p2, p3 = st.columns([1, 1, 2])
            with p1:
                if st.button("上一页", disabled=st.session_state.flow_b_jd_page <= 1, key="fb_jd_prev"):
                    st.session_state.flow_b_jd_page -= 1
                    st.rerun()
            with p2:
                if st.button("下一页", disabled=st.session_state.flow_b_jd_page >= max_page, key="fb_jd_next"):
                    st.session_state.flow_b_jd_page += 1
                    st.rerun()
            with p3:
                st.caption(f"共 {total} 条 · 第 {st.session_state.flow_b_jd_page}/{max_page} 页")
            rows = list_visible_jds(
                st.session_state.db,
                current_user_id(),
                search=jd_search or None,
                limit=page_size,
                offset=(st.session_state.flow_b_jd_page - 1) * page_size,
            )
            options = {f"{r.get('title') or '未命名'} @ {r.get('company') or '未知公司'} ({r.get('source')})": r["id"] for r in rows}
            selected = st.selectbox("选择 JD", list(options.keys()) if options else ["JD库暂无内容"])
            if options and st.button("使用这个 JD"):
                jd = get_visible_jd(st.session_state.db, current_user_id(), options[selected])
                st.session_state.jd_id = jd["id"]
                st.session_state.jd_result = {
                    "title": jd.get("title", ""),
                    "company": jd.get("company", ""),
                    "location": jd.get("location", ""),
                    "core_requirements": jd.get("parsed_sections", {}).get("requirements", []),
                    "keywords": jd.get("tags", []),
                    "raw_text": jd.get("raw_text", ""),
                }
                st.success("已选择 JD。")
        else:
            jd_url = st.text_input("职位 URL")
            if st.button("从 URL 分析 JD", disabled=not jd_url):
                with st.spinner("正在抓取并分析 JD..."):
                    analyzer = JDAnalyzerEnhanced(llm_client=st.session_state.llm_client)
                    jd_result = run_async(analyzer.parse_from_url(jd_url))
                    raw_text = jd_result.get("raw_text", jd_url)
                    jd_payload = jd_to_db_payload(raw_text, jd_result, current_user_id(), source="url")
                    jd_payload["url"] = jd_url
                    jd_id = insert_user_jd(st.session_state.db, current_user_id(), jd_payload)
                    embed_and_store_jd_chunks(st.session_state.db, jd_id, raw_text, user_id=current_user_id())
                    log_action(
                        st.session_state.db,
                        user_id=current_user_id(),
                        action="jd.create",
                        target_table="jds",
                        target_id=jd_id,
                        details={"flow": "b", "source": "url", "url": jd_url[:200]},
                    )
                    st.session_state.jd_result = jd_result
                    st.session_state.jd_id = jd_id
                    st.success("JD 已分析并保存。")
        if st.session_state.jd_result:
            st.json(st.session_state.jd_result, expanded=False)

    with st.expander("3. 匹配度分析", expanded=st.session_state.resume_data is not None and st.session_state.jd_result is not None):
        if st.button("分析匹配度", type="primary", disabled=not st.session_state.resume_data or not st.session_state.jd_result):
            with st.spinner("正在分析匹配度..."):
                agent = st.session_state.agent
                agent.state["resume_data"] = st.session_state.resume_data
                agent.state["jd_result"] = st.session_state.jd_result
                result = run_async(agent._tool_analyze_match())
                match_result = result.get("match_result", result)
                st.session_state.match_result = match_result
                score = match_result.get("score", 0)
                st.session_state.last_match_score = score
                if st.session_state.resume_id and st.session_state.jd_id:
                    st.session_state.last_match_id = st.session_state.db.insert_match({
                        "user_id": current_user_id(),
                        "resume_id": st.session_state.resume_id,
                        "jd_id": st.session_state.jd_id,
                        "score": score,
                        "reasoning": match_result.get("reasoning", ""),
                        "matched_skills": match_result.get("matched_skills", []),
                        "missing_skills": match_result.get("missing_skills", []),
                        "gaps": match_result.get("gaps", []),
                        "recommendations": match_result.get("recommendations", []),
                        "skill_mapping": match_result.get("skill_mapping", []),
                    })
                    log_action(
                        st.session_state.db,
                        user_id=current_user_id(),
                        action="match.create",
                        target_table="match_history",
                        target_id=st.session_state.last_match_id,
                        details={"score": score, "resume_id": st.session_state.resume_id, "jd_id": st.session_state.jd_id},
                    )
                    opt_ids = []
                    for rec in match_result.get("recommendations", []):
                        opt_ids.append(st.session_state.db.insert_optimization({
                            "user_id": current_user_id(),
                            "resume_id": st.session_state.resume_id,
                            "jd_id": st.session_state.jd_id,
                            "optimization_type": rec.get("type", "modify"),
                            "section": rec.get("section", ""),
                            "original_content": rec.get("original", ""),
                            "suggested_content": rec.get("suggestion", ""),
                            "reason": rec.get("reason", ""),
                        }))
                    if opt_ids:
                        log_action(
                            st.session_state.db,
                            user_id=current_user_id(),
                            action="optimization.create",
                            target_table="optimizations",
                            target_id=opt_ids[0],
                            details={"count": len(opt_ids), "match_id": st.session_state.last_match_id},
                        )
                    st.session_state.last_opt_ids = opt_ids
                st.success("匹配分析完成。")
        if st.session_state.match_result:
            match = st.session_state.match_result
            st.metric("匹配度", f"{match.get('score', 0)}%")
            if match.get("reasoning"):
                st.write(match["reasoning"])
            if match.get("matched_skills"):
                st.markdown("**已匹配技能**")
                st.write("、".join(match["matched_skills"]))
            if match.get("missing_skills"):
                st.markdown("**缺失技能**")
                st.write("、".join(match["missing_skills"]))
            if match.get("recommendations"):
                st.markdown("**优化建议**")
                for rec in match["recommendations"]:
                    st.markdown(f"- **{rec.get('section', '')}**：{rec.get('reason') or rec.get('suggestion', '')}")

    render_generation_toolbar()
    st.divider()
    st.session_state.flow_b_company_name = st.text_input("目标公司名（用于 Cover Letter）", value=st.session_state.flow_b_company_name or (st.session_state.jd_result or {}).get("company", ""))
    if st.session_state.optimized_resume:
        st.markdown("### 优化后简历")
        st.markdown(st.session_state.optimized_resume)
        st.download_button("下载优化简历 Markdown", st.session_state.optimized_resume, file_name="optimized_resume.md", mime="text/markdown")
        if st.session_state.optimized_resume_html:
            st.download_button("下载优化简历 HTML", st.session_state.optimized_resume_html, file_name="optimized_resume.html", mime="text/html")
    if st.session_state.cover_letter:
        st.markdown("### Cover Letter")
        st.markdown(st.session_state.cover_letter)
        st.download_button("下载 Cover Letter", st.session_state.cover_letter, file_name="cover_letter.txt", mime="text/plain")


# ---------------------------------------------------------------------------
# JD library
# ---------------------------------------------------------------------------


def render_resume_library() -> None:
    """「我的简历」页面：版本树管理 + 主简历切换 + 克隆新版本。"""
    from services.resume_library_service import list_resumes_flat

    render_top_nav()
    st.header("我的简历")
    st.caption("管理你所有简历版本。切换「主简历」后，求职匹配 / 优化都会默认用它。")

    db = st.session_state.db
    if db is None:
        st.error("数据库未初始化。")
        return

    # 优先显示 current_user_id() 的简历；如果为空，回退到 default（dev 期数据）
    primary_user = current_user_id()
    flat = list_resumes_flat(db, primary_user)
    fallback_user = None
    if not flat:
        flat = db.list_resumes("default")
        fallback_user = "default"

    if not flat:
        st.info("还没有任何简历。先去首页用 Flow A 生成一份，或在 Flow B 里上传 PDF。")
        return

    if fallback_user:
        st.warning(
            f"当前账号 `{primary_user}` 下无简历，临时显示 user_id=`{fallback_user}` 的历史简历。"
        )
        effective_user = fallback_user
    else:
        effective_user = primary_user

    # 在 session_state 里记当前 effective_user，on_change callback 用得到
    st.session_state._resume_lib_effective_user = effective_user

    primary = get_primary_resume(db, effective_user)
    if primary:
        st.success(
            f"**当前主简历**：v{primary.get('version') or 1} · {primary.get('name') or '(未命名)'} · "
            f"{_short_time(primary.get('updated_at'))}"
        )
    else:
        st.info("还没有设置主简历——在下面版本行点「设为主简历」。")

    trees = list_resume_versions(db, effective_user)
    for tree in trees:
        with st.expander(
            f"📁 {tree['root_label']} · 共 {len(tree['versions'])} 个版本",
            expanded=(tree["root_id"] == (primary["id"] if primary else None)),
        ):
            _render_version_tree(db, effective_user, tree)


def _render_version_tree(db, user_id: str, tree: Dict[str, Any]) -> None:
    """渲染单个版本树（含克隆 / 切换主 / 删除操作）。"""
    for v in tree["versions"]:
        is_primary = bool(v.get("is_primary"))
        label = v.get("version_label") or ""
        name = v.get("name") or "(未命名)"
        summary = (v.get("summary") or "").strip()
        cols = st.columns([1, 4, 2])
        with cols[0]:
            star = "⭐ " if is_primary else ""
            st.markdown(f"**{star}v{v.get('version') or 1}**")
            st.caption(_short_time(v.get("updated_at")))
        with cols[1]:
            st.markdown(f"**{name}**" + (f" · _{label}_" if label else ""))
            if summary:
                st.caption(summary[:140] + ("…" if len(summary) > 140 else ""))
            skills = v.get("skills") or []
            if skills and isinstance(skills, list):
                tags = " · ".join(f"`{s}`" for s in skills[:6] if s)
                if tags:
                    st.caption(f"技能：{tags}")
        with cols[2]:
            act_cols = st.columns(3)
            with act_cols[0]:
                if not is_primary and st.button("设为主", key=f"prim_{v['id']}", use_container_width=True):
                    try:
                        set_primary_resume(db, user_id, v["id"])
                        log_action(
                            db, user_id=user_id, action="resume.set_primary",
                            target_table="resumes", target_id=v["id"],
                        )
                        st.rerun()
                    except ResumeLibraryError as exc:
                        st.error(str(exc))
            with act_cols[1]:
                if st.button("克隆", key=f"clone_{v['id']}", use_container_width=True):
                    st.session_state[f"_show_clone_{v['id']}"] = True
            with act_cols[2]:
                if st.button("删除", key=f"del_{v['id']}", use_container_width=True):
                    db.soft_delete_resume(v["id"])
                    log_action(
                        db, user_id=user_id, action="resume.soft_delete",
                        target_table="resumes", target_id=v["id"],
                    )
                    st.rerun()

        # 克隆表单（按需展开）
        if st.session_state.get(f"_show_clone_{v['id']}"):
            with st.form(key=f"clone_form_{v['id']}"):
                st.markdown(f"基于 **v{v.get('version') or 1} · {name}** 创建新版本")
                new_label = st.text_input(
                    "版本标签（可选）",
                    placeholder="例如：针对字节跳动 JD 优化",
                    key=f"clone_label_{v['id']}",
                )
                new_name = st.text_input(
                    "新版本姓名（留空则与父版本相同）",
                    value=name,
                    key=f"clone_name_{v['id']}",
                )
                submitted = st.form_submit_button("创建新版本")
                cancel = st.form_submit_button("取消")
                if submitted:
                    overrides = {"name": new_name} if new_name != name else {}
                    if new_label:
                        overrides["version_label"] = new_label
                    new_id = clone_resume(db, v["id"], user_id, overrides=overrides)
                    log_action(
                        db, user_id=user_id, action="resume.clone",
                        target_table="resumes", target_id=new_id,
                        details={"source_id": v["id"]},
                    )
                    st.session_state[f"_show_clone_{v['id']}"] = False
                    st.success(f"已创建新版本，id={new_id[:12]}…")
                    st.rerun()
                if cancel:
                    st.session_state[f"_show_clone_{v['id']}"] = False
                    st.rerun()


# ---------------------------------------------------------------------------
# JD library metadata helpers (M11 / PR2)
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
    from datetime import datetime, timezone

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

    sal = _jd_salary_chip(jd)
    if sal:
        chips.append(sal)

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
        text = f"数据质量 {label}"
        if quality_score is not None:
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
        from datetime import datetime, timezone

        result = compute_jd_quality(jd)
        now_iso = datetime.now(timezone.utc).isoformat()
        db.update_jd_quality_score(jd["id"], result["composite"], now_iso)
        return result["composite"]
    except Exception:
        return None


# PR6 (M12): PDF 异步生成 — 后台线程先出 MD/HTML，PDF 在跑就 disabled 按钮
def _kick_off_background_pdf(html_str: str) -> None:
    """后台线程启动 PDF 生成；状态写到 session_state。

    fa_pdf_status 取值：
      "pending" — 后台线程跑中或尚未开始
      "ready"   — PDF 准备好，bytes 在 fa_resume_pdf
      "failed"  — 出错，err 在 fa_pdf_error
    """
    if st.session_state.get("fa_pdf_status") in (None, "ready"):
        # ready 表示已生成；None 表示尚未启动
        if st.session_state.get("fa_pdf_status") == "ready":
            return
        st.session_state.fa_pdf_status = "pending"
        st.session_state.fa_pdf_error = None

        import threading

        def _worker():
            try:
                from tools.generator.resume_pdf import html_to_pdf_safe
                pdf_bytes = html_to_pdf_safe(html_str)
                # 写到 thread-local dict，UI 通过 _poll_pdf_status 读
                _PDF_RESULT["bytes"] = pdf_bytes
                _PDF_RESULT["status"] = "ready"
            except Exception as exc:  # pragma: no cover
                _PDF_RESULT["error"] = str(exc)
                _PDF_RESULT["status"] = "failed"

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()


# 模块级容器，存后台线程结果（避免 st.session_state 在 worker 里写主线程状态）
_PDF_RESULT: Dict[str, Any] = {}


def _poll_pdf_status() -> None:
    """每次 rerun 同步一次后台结果到 session_state。轻量级。"""
    if st.session_state.get("fa_pdf_status") != "pending":
        return
    s = _PDF_RESULT.get("status")
    if s == "ready":
        st.session_state.fa_resume_pdf = _PDF_RESULT.get("bytes")
        st.session_state.fa_pdf_status = "ready"
    elif s == "failed":
        st.session_state.fa_pdf_error = _PDF_RESULT.get("error")
        st.session_state.fa_pdf_status = "failed"
    else:
        # 后台还没好，1.5s 后自动 rerun 检查一次
        import time

        time.sleep(1.5)
        st.rerun()


# PR3 (M11): Flow A 收尾"改写依据"面板。基于 build_skeleton 输出的 source_breakdown。
_PLATFORM_LABEL_FA = {
    "51job": "51job",
    "jobsdb": "JobsDB",
    "liepin": "猎聘",
    "boss": "Boss",
    "zhilian": "智联",
    "other": "其他",
}


# PR5 (M12): Flow A 粘贴抽取通道（推荐路径）
def _render_flow_a_paste_panel(flow_a) -> None:
    """粘贴完整文本 → 一次性结构化抽取 → 可编辑 → 确认。

    一次展示 experience + projects 两块。点击"一键解析"后两个 section
    都跑 LLM 一次性抽取（而非逐段聊天），结果用 st.data_editor 让用户
    微调，最后"确认 → 跳过对话采集"标记两 section done 并跳 Step 4。"""
    st.markdown(
        '<div class="step-help">粘贴你现有简历里的工作经历 / 项目经历，'
        'AI 会一次性抽出，10 秒左右出结果。也可以下拉切换到「逐段对话」。</div>',
        unsafe_allow_html=True,
    )

    exp_text = st.text_area(
        "粘贴工作经历（一段一段，AI 会自动拆条）",
        value=st.session_state.get("fa_paste_experience", ""),
        key="fa_paste_experience_input",
        height=220,
        placeholder="例：\n2022-2024 ACME AI 产品经理\n- 主导 XX 项目，...",
    )
    proj_text = st.text_area(
        "粘贴项目经历（同上）",
        value=st.session_state.get("fa_paste_projects", ""),
        key="fa_paste_projects_input",
        height=160,
        placeholder="例：\n智能客服系统 / 角色：PM / 技术栈：... / 成果：...",
    )

    c_parse, c_skip, _ = st.columns([1, 1, 4])
    with c_parse:
        parse_clicked = st.button(
            "✨ 一键解析（10 秒）",
            type="primary",
            disabled=not (exp_text.strip() or proj_text.strip()),
        )
    with c_skip:
        if st.button("跳过本节，直接生成"):
            for key in ["experience", "projects"]:
                if key not in st.session_state.fa_section_skipped:
                    st.session_state.fa_section_skipped.append(key)
                if key in st.session_state.fa_section_done:
                    st.session_state.fa_section_done.remove(key)
            st.session_state.fa_section_index = len(_flow_a_collect_sections())
            _invalidate_flow_a_generation()
            _save_flow_a_draft("generate", None)
            st.rerun()

    if parse_clicked:
        try:
            experience = run_async(flow_a.extract_from_paste("experience", exp_text)) if exp_text.strip() else []
            projects = run_async(flow_a.extract_from_paste("projects", proj_text)) if proj_text.strip() else []
            st.session_state["fa_paste_parsed_experience"] = experience
            st.session_state["fa_paste_parsed_projects"] = projects
            st.success("解析完成，可微调后确认。")
        except Exception as exc:
            st.session_state.fa_last_error = str(exc)
            current_section = _flow_a_collect_sections()[st.session_state.fa_section_index]["key"]
            _save_flow_a_draft("collect", current_section, last_error=str(exc))
            st.error(f"解析失败：{exc}")

    parsed_exp = st.session_state.get("fa_paste_parsed_experience")
    parsed_proj = st.session_state.get("fa_paste_parsed_projects")
    if parsed_exp is not None or parsed_proj is not None:
        st.markdown("#### 解析结果（可编辑）")
        if parsed_exp is not None:
            st.caption(f"工作经历：抽到 {len(parsed_exp)} 条")
            edited_exp = st.data_editor(
                parsed_exp,
                key="fa_paste_edit_experience",
                num_rows="dynamic",
                use_container_width=True,
            )
        else:
            edited_exp = parsed_exp

        if parsed_proj is not None:
            st.caption(f"项目经历：抽到 {len(parsed_proj)} 条")
            edited_proj = st.data_editor(
                parsed_proj,
                key="fa_paste_edit_projects",
                num_rows="dynamic",
                use_container_width=True,
            )
        else:
            edited_proj = parsed_proj

        c_confirm, c_back, _ = st.columns([1, 1, 4])
        with c_confirm:
            if st.button("✅ 确认 → 跳过对话采集", type="primary"):
                exp_data = edited_exp if isinstance(edited_exp, list) else ([edited_exp] if edited_exp else [])
                proj_data = edited_proj if isinstance(edited_proj, list) else ([edited_proj] if edited_proj else [])

                # 粘贴为空代表用户明确不提供该可选段，按 skipped 处理；有内容则必须先过本地 validator。
                if exp_data:
                    if not _apply_flow_a_section_extracted("experience", exp_data):
                        st.rerun()
                else:
                    if "experience" not in st.session_state.fa_section_skipped:
                        st.session_state.fa_section_skipped.append("experience")
                    st.session_state.fa_section_index = max(st.session_state.fa_section_index, 1)

                if proj_data:
                    if not _apply_flow_a_section_extracted("projects", proj_data):
                        st.rerun()
                else:
                    if "projects" not in st.session_state.fa_section_skipped:
                        st.session_state.fa_section_skipped.append("projects")
                    st.session_state.fa_section_index = len(_flow_a_collect_sections())
                    _save_flow_a_draft("generate", None)

                st.success("已应用粘贴结果，进入简历生成阶段。")
                st.rerun()
        with c_back:
            if st.button("↩ 返回逐段对话"):
                st.session_state["fa_extract_mode"] = "chat"
                st.rerun()


def _render_flow_a_provenance_panel(skeleton: Dict) -> None:
    """渲染 Flow A 末尾的"基于哪些 JD 改写"面板。

    skeleton 是 build_skeleton() 的输出。空 / fallback 时显示醒目警告。"""
    source = skeleton.get("source", "fallback")
    n_chunks = int(skeleton.get("n_chunks", 0) or 0)
    breakdown = skeleton.get("source_breakdown") or {}

    chips = []
    if n_chunks > 0:
        chips.append(f"改写基于 <b>{n_chunks}</b> 条 JD chunk")
    n_companies = int(breakdown.get("n_companies") or 0)
    if n_companies > 0:
        chips.append(f"覆盖 <b>{n_companies}</b> 家公司")
    plat_counts = breakdown.get("platform_counts") or {}
    if plat_counts:
        plat_chips = []
        for plat, cnt in sorted(plat_counts.items(), key=lambda kv: -kv[1])[:5]:
            label = _PLATFORM_LABEL_FA.get(plat, plat)
            plat_chips.append(f'<span class="jd-meta-chip jd-meta-chip-platform">{label}({cnt})</span>')
        chips.append("来源：" + " ".join(plat_chips))

    if chips:
        # 来源 line 嵌入 platform chips，其余用普通 caption 风格
        head = chips[0]
        rest = " · ".join(chips[1:])
        if plat_counts:
            # rest 中最后一项是 "来源：...chips..."
            head_and_rest = " · ".join(chips[:-1]) + " · " + chips[-1]
            st.markdown(head_and_rest, unsafe_allow_html=True)
        else:
            st.caption(" · ".join(chips))
    else:
        st.caption("本轮未做 RAG 改写。")

    if source == "fallback":
        st.warning(
            "本岗位在 JD 库内未命中高质量样本，已回退通用模板。"
            "建议你换一个更具体的岗位关键词，或先到 JD 库挑几条相关 JD 后再生成。"
        )

    top_chunks: List[Dict] = breakdown.get("top_chunks") or []
    if top_chunks:
        with st.expander(f"查看改写依据 (Top {len(top_chunks)})"):
            for i, c in enumerate(top_chunks, 1):
                plat = _PLATFORM_LABEL_FA.get(c.get("platform") or "", "其他")
                text = (c.get("chunk_text") or "")[:160].replace("\n", " ").strip()
                sim = c.get("similarity") or 0.0
                st.markdown(
                    f"**{i}.** <span class='jd-meta-chip jd-meta-chip-platform'>{plat}</span> "
                    f"`相似度 {sim:.2f}`<br/>"
                    f"<span style='color:#94a3b8;font-size:0.85rem'>{text}…</span>",
                    unsafe_allow_html=True,
                )


def _short_time(iso: Optional[str]) -> str:
    if not iso:
        return ""
    return iso.replace("T", " ")[:16]


def render_jd_library() -> None:
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
        jd_text = st.text_area("粘贴 JD", height=220, key="jd_library_add_text")
        if st.button("分析并保存到 JD库", disabled=not jd_text):
            if not require_services():
                return
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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


init_session_state()
init_app_services()

if st.session_state.app_route == "landing":
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
