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

from agents.coordinator.orchestrator import CoordinatorAgent
from agents.resume_flow_a import ResumeFlowA, SECTIONS
from config.settings import settings
from database.classifier import Classifier
from database.factory import get_db
from services.audit_service import log_action
from services.auth_service import AuthError, AuthService
from services.quota_service import QuotaExceededError, QuotaService
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


# ---------------------------------------------------------------------------
# Flow A
# ---------------------------------------------------------------------------


# v3 M-rebuild-2 Step 1: JD 三选一入口（text / image / rag）
#
# 设计（update_plan §1.2 + §8.2 Q1 已解）：
# - 行业×职能×岗位下拉保留 = RAG 入口（确认时调 JDParserRouter.parse(source="rag", ...)）
# - 旁加"粘贴文本 / 上传图片"两个备选按钮
# - 三路径统一经 JDParserRouter.parse() 入库到 fa_jd_structured
# - OCR 路径强制 needs_user_review=True，前端必须给校对界面
# - RAG / text 路径若 needs_user_review=False，可跳过校对直接进 Step 2
# - 当前 Step 完成 → fa_step += 1，进入 Step 2
def render_flow_a_step_1_jd_input() -> None:
    """v3 Step 1: JD 输入（三选一）+ 校对 + 入库。"""
    st.markdown('<span class="step-pill">第 1 步</span>确定目标 JD', unsafe_allow_html=True)
    st.caption("三种方式选一：① 选行业/职能/岗位从 JD 库调 ② 粘贴 JD 文本 ③ 上传 JD 截图。")

    mode = st.radio(
        "JD 输入方式",
        options=["rag", "text", "image"],
        format_func=lambda m: {
            "rag": "从行业/职能/岗位推荐（JD 库）",
            "text": "粘贴 JD 文本",
            "image": "上传 JD 截图（OCR）",
        }[m],
        key="fa_jd_input_mode_radio",
        index=["rag", "text", "image"].index(st.session_state.get("fa_jd_input_mode", "rag")),
        horizontal=True,
    )
    # 同步到 session_state（供下游使用）
    st.session_state.fa_jd_input_mode = mode

    jd: Optional[Dict[str, Any]] = st.session_state.get("fa_jd_structured")
    needs_review = bool(jd and jd.get("needs_user_review"))
    review_done = bool(st.session_state.get("fa_jd_review_done"))

    if mode == "rag":
        _render_jd_rag_panel()
    elif mode == "text":
        _render_jd_text_panel()
    else:
        _render_jd_image_panel()

    # 校对界面（仅在 needs_user_review=True 时显示）
    if jd and needs_review and not review_done:
        st.divider()
        st.markdown("##### ⚠️ 需要你校对")
        st.caption("OCR / LLM 抽取可能有误差，请逐项确认后再继续。")
        _render_jd_review_form(jd)
        return

    # 解析结果摘要（确认后才显示）
    if jd and (review_done or not needs_review):
        st.divider()
        with st.container(border=True):
            st.markdown("##### 当前 JD")
            c1, c2, c3 = st.columns(3)
            with c1:
                st.write(f"**公司**：{jd.get('company') or '（未识别）'}")
            with c2:
                st.write(f"**岗位**：{jd.get('title') or '（未识别）'}")
            with c3:
                st.write(f"**来源**：{jd.get('source')}")
            if jd.get("industry") or jd.get("function"):
                st.write(
                    f"**行业 × 职能**：{jd.get('industry', '-')} / {jd.get('function', '-')}"
                    + (f" / {jd.get('level')}" if jd.get("level") else "")
                )
            if jd.get("responsibilities"):
                with st.expander(f"职责（{len(jd['responsibilities'])} 条）", expanded=False):
                    for r in jd["responsibilities"]:
                        st.write(f"- {r}")
            if jd.get("requirements"):
                with st.expander(f"要求（{len(jd['requirements'])} 条）", expanded=False):
                    for r in jd["requirements"]:
                        st.write(f"- {r}")
            if jd.get("parse_notes"):
                with st.expander("解析备注", expanded=False):
                    for n in jd["parse_notes"]:
                        st.caption(f"· {n}")
            # 操作：重新解析 / 下一步
            op1, op2, op3 = st.columns([1, 1, 3])
            with op1:
                if st.button("重新选择", key="fa_step1_repick"):
                    st.session_state.fa_jd_structured = None
                    st.session_state.fa_jd_review_done = False
                    st.rerun()
            with op2:
                if st.button("下一步", type="primary", key="fa_step1_next"):
                    st.session_state.fa_step = 2
                    _save_flow_a_draft("basic_form", None)
                    st.rerun()


def _render_jd_rag_panel() -> None:
    """RAG 路径：行业/职能/岗位下拉 + JDParserRouter.parse(source='rag', ...)。"""
    col_i, col_f, col_p = st.columns(3)
    with col_i:
        industries = taxonomy.list_industries()
        industry = st.selectbox(
            "行业", ["(请选择)"] + industries, key="fa_step1_rag_industry"
        )
    with col_f:
        functions = taxonomy.list_functions(industry) if industry != "(请选择)" else []
        function = st.selectbox(
            "职能",
            ["(请选择)"] + functions if functions else ["(请先选行业)"],
            key="fa_step1_rag_function",
            disabled=not functions,
        )
    with col_p:
        positions = (
            taxonomy.list_positions(industry, function)
            if industry != "(请选择)" and function and function != "(请选择)"
            else []
        )
        position = st.selectbox(
            "岗位",
            ["(请选择)"] + positions if positions else ["(请先选职能)"],
            key="fa_step1_rag_position",
            disabled=not positions,
        )

    level = st.selectbox(
        "级别（可选）",
        ["（不限）", "junior", "mid", "senior"],
        key="fa_step1_rag_level",
    )
    can_run = (
        industry != "(请选择)" and function and function != "(请选择)"
        and position and position != "(请选择)"
    )
    if st.button("从 JD 库调出", type="primary", disabled=not can_run, key="fa_step1_rag_run"):
        st.session_state.fa_jd_industry = industry
        st.session_state.fa_jd_function = function
        st.session_state.fa_jd_level = None if level == "（不限）" else level
        with st.spinner("调取 RAG 库中…"):
            try:
                from services.jd_parser import JDParserRouter
                router = JDParserRouter(
                    llm_client=st.session_state.get("llm_client"),
                    db=st.session_state.get("db"),
                )
                jd_obj = run_async(router.parse(
                    source="rag",
                    input={
                        "industry": industry,
                        "function": function,
                        "level": None if level == "（不限）" else level,
                        "position": position,
                    },
                ))
                jd_dict = _jd_to_dict(jd_obj)
                st.session_state.fa_jd_structured = jd_dict
                st.session_state.fa_jd_review_done = (
                    not jd_dict.get("needs_user_review", False)
                )
                st.success(
                    f"已调出（{jd_dict.get('parse_notes', ['RAG 库'])[0]}）"
                    if jd_dict.get("parse_notes") else "已调出"
                )
                st.rerun()
            except Exception as exc:
                st.error(f"RAG 调取失败：{exc}")


def _render_jd_text_panel() -> None:
    """Text 路径：text_area + JDParserRouter.parse(source='text', ...)。"""
    text = st.text_area(
        "把 JD 完整粘贴到这里",
        value=st.session_state.get("fa_jd_text_input", ""),
        height=240,
        key="fa_step1_text_input",
        placeholder="示例：\n字节跳动 / AI 产品经理\n岗位职责：\n1. 负责 LLM 应用的需求分析…\n2. …\n任职要求：\n1. 本科及以上…\n",
    )
    # 同步到 session_state 以便提交按钮读取最新值
    st.session_state.fa_jd_text_input = text
    if st.button("解析", type="primary", disabled=not text.strip(), key="fa_step1_text_run"):
        with st.spinner("LLM 解析中…"):
            try:
                from services.jd_parser import JDParserRouter
                router = JDParserRouter(
                    llm_client=st.session_state.get("llm_client"),
                    db=st.session_state.get("db"),
                )
                jd_obj = run_async(router.parse(source="text", input=text))
                jd_dict = _jd_to_dict(jd_obj)
                st.session_state.fa_jd_structured = jd_dict
                st.session_state.fa_jd_review_done = (
                    not jd_dict.get("needs_user_review", False)
                )
                st.rerun()
            except Exception as exc:
                st.error(f"解析失败：{exc}")


def _render_jd_image_panel() -> None:
    """Image 路径：file_uploader + PaddleOCR + JDParserRouter.parse(source='image', ...)。

    OCR 不可信 → 强制 needs_user_review=True，强制走校对界面（见 render_flow_a_step_1_jd_input）。
    """
    uploaded = st.file_uploader(
        "上传 JD 截图（PNG / JPG）",
        type=["png", "jpg", "jpeg", "webp", "bmp"],
        key="fa_step1_image_upload",
    )
    if uploaded is not None:
        # 保存到临时路径（ImageJDParser.parse 接文件路径）
        import tempfile
        suffix = "." + uploaded.name.split(".")[-1] if "." in uploaded.name else ".png"
        tmp = tempfile.NamedTemporaryFile(
            delete=False, suffix=suffix, dir=tempfile.gettempdir()
        )
        tmp.write(uploaded.read())
        tmp.close()
        st.session_state.fa_jd_image_path = tmp.name
        st.caption(f"已保存到：{tmp.name}")
    if st.button(
        "OCR + 解析",
        type="primary",
        disabled=not st.session_state.get("fa_jd_image_path"),
        key="fa_step1_image_run",
    ):
        with st.spinner("OCR + LLM 抽结构中（约 10s）…"):
            try:
                from services.jd_parser import JDParserRouter
                router = JDParserRouter(
                    llm_client=st.session_state.get("llm_client"),
                    db=st.session_state.get("db"),
                )
                jd_obj = run_async(router.parse(
                    source="image", input=st.session_state.fa_jd_image_path,
                ))
                jd_dict = _jd_to_dict(jd_obj)
                # 强制走校对（即使 OCR 解析后 needs_user_review=False 也强制）
                jd_dict["needs_user_review"] = True
                st.session_state.fa_jd_structured = jd_dict
                st.session_state.fa_jd_review_done = False
                st.rerun()
            except Exception as exc:
                st.error(f"OCR 解析失败：{exc}")


def _render_jd_review_form(jd: Dict[str, Any]) -> None:
    """OCR / LLM 解析后的校对表单（用户可改字段 + 确认入库）。"""
    with st.form("fa_step1_review_form"):
        st.caption(f"原始文本预览：\n```\n{(jd.get('raw_text') or '')[:600]}\n```")
        c1, c2 = st.columns(2)
        with c1:
            company = st.text_input("公司", value=jd.get("company") or "", key="fa_step1_rev_company")
            industry = st.text_input("行业", value=jd.get("industry") or "", key="fa_step1_rev_industry")
        with c2:
            title = st.text_input("岗位", value=jd.get("title") or "", key="fa_step1_rev_title")
            function = st.text_input("职能", value=jd.get("function") or "", key="fa_step1_rev_function")
        responsibilities = st.text_area(
            "职责（每行一条）",
            value="\n".join(jd.get("responsibilities") or []),
            height=120,
            key="fa_step1_rev_resp",
        )
        requirements = st.text_area(
            "要求（每行一条）",
            value="\n".join(jd.get("requirements") or []),
            height=120,
            key="fa_step1_rev_req",
        )
        submitted = st.form_submit_button("确认无误，下一步", type="primary")
    if submitted:
        jd["company"] = company.strip() or None
        jd["title"] = title.strip() or None
        jd["industry"] = industry.strip() or None
        jd["function"] = function.strip() or None
        jd["responsibilities"] = [r.strip() for r in responsibilities.splitlines() if r.strip()]
        jd["requirements"] = [r.strip() for r in requirements.splitlines() if r.strip()]
        jd["needs_user_review"] = False
        st.session_state.fa_jd_structured = jd
        st.session_state.fa_jd_review_done = True
        st.rerun()


def _jd_to_dict(jd_obj: Any) -> Dict[str, Any]:
    """StructuredJD（dataclass）→ dict（Streamlit session_state 友好）。"""
    if jd_obj is None:
        return {}
    if isinstance(jd_obj, dict):
        return jd_obj
    if hasattr(jd_obj, "to_db_dict"):
        d = jd_obj.to_db_dict()
        d["needs_user_review"] = getattr(jd_obj, "needs_user_review", False)
        d["parse_notes"] = list(getattr(jd_obj, "parse_notes", []) or [])
        d["raw_text"] = getattr(jd_obj, "raw_text", "")
        d["level"] = getattr(jd_obj, "level", None)
        d["user_id"] = getattr(jd_obj, "user_id", "default")
        return d
    if hasattr(jd_obj, "__dict__"):
        return vars(jd_obj)
    return {}


def _sync_flow_a_position_from_jd() -> None:
    """把 fa_jd_structured 同步到兼容旧逻辑的 fa_position / fa_industry / fa_function。

    旧 flow_a 后续步骤（Step 2-4 的兼容路径）会读 fa_position；
    新 v3 步骤（Step 5+）直接读 fa_jd_structured。
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
    # v3 5-step state machine 分发
    _sync_flow_a_position_from_jd()
    fa_step = st.session_state.get("fa_step", 1)
    if fa_step == 1:
        render_flow_a_step_1_jd_input()
        return
    if fa_step == 2:
        render_flow_a_step_2_form()
        return
    if fa_step == 3:
        render_flow_a_step_3_rewrite()
        return
    if fa_step == 4:
        render_flow_a_step_4_preview()
        return
    if fa_step == 5:
        render_flow_a_step_5_export()
        return
    # Step 6+ 暂沿用 v2.1 的 4 步旧逻辑
    render_flow_a_legacy_steps()


# v3 round-2 Step 2: 渐进式披露表单（基本+教育+工作+项目+技能）
#
# 设计（update_plan §1.1）：
# - 默认最小集：1 段教育 + 1 段工作 + 0 段项目
# - `+ 添加` 按钮显式扩展
# - "成果数据"独立字段（HR 最看重的数字）
# - 技能/证书/语言/作品集折叠区（默认收起）
# - 所有字段存在 st.session_state["fa_step2_form"] dict 里
def render_flow_a_step_2_form() -> None:
    """v3 Step 2: 渐进式披露表单。"""
    form = _ensure_step2_form()

    st.markdown('<span class="step-pill">第 2 步</span>填写简历内容', unsafe_allow_html=True)
    target = (st.session_state.get("fa_jd_structured") or {}).get("title") or \
        st.session_state.get("fa_position") or "（未选岗位）"
    st.caption(f"目标岗位：{target} — 填一次表，能产出多份匹配不同岗位的简历。")

    # 上一步 / 重置
    op_back, op_reset_draft, op_reset_all, _ = st.columns([1, 1, 1, 3])
    with op_back:
        if st.button("← 返回 Step 1 改 JD", key="fa_step2_back"):
            st.session_state.fa_step = 1
            st.rerun()
    with op_reset_draft:
        # P1-1：只清空 Step 2-5 表单数据，保留 Step 1 的 JD 选择
        if st.button("🗑 重置草稿", key="fa_step2_reset_draft",
                     help="只清空 Step 2-5 表单 / 改写 / 预览 / 导出，保留 Step 1 的 JD 选择"):
            reset_flow_a_v3_step_state()
            st.rerun()
    with op_reset_all:
        if st.button("重新开始", key="fa_step2_reset",
                     help="彻底清空（连 JD 选择一起）"):
            reset_flow_a_state()
            st.rerun()

    # ---------------- 基本信息（始终展开） ----------------
    with st.expander("### 基本信息（必填）", expanded=True):
        _render_step2_basic(form["basic"])

    # ---------------- 教育经历 ----------------
    with st.expander(f"### 教育经历（{len(form['education'])} 段）", expanded=True):
        _render_step2_education_list(form)

    # ---------------- 工作经历 ----------------
    with st.expander(f"### 工作经历（{len(form['work'])} 段）", expanded=True):
        _render_step2_work_list(form)

    # ---------------- 项目经历（默认折叠） ----------------
    with st.expander(f"### 项目经历（{len(form['projects'])} 段，可选）", expanded=False):
        _render_step2_project_list(form)

    # ---------------- 折叠区：技能 / 证书 / 语言 / 作品集 ----------------
    with st.expander("### 技能 / 证书 / 语言 / 作品集（可选）", expanded=False):
        _render_step2_optional(form)

    # ---------------- 提交 ----------------
    st.divider()
    if st.button("保存并继续到 Step 3（改写）", type="primary", key="fa_step2_next"):
        err = _validate_step2_form(form)
        if err:
            st.error(err)
        else:
            st.session_state.fa_step2_form = form
            st.session_state.fa_step = 3
            st.rerun()


def _ensure_step2_form() -> Dict[str, Any]:
    """确保 fa_step2_form 存在（首次进入 Step 2 初始化默认值）。"""
    if "fa_step2_form" in st.session_state and st.session_state.fa_step2_form:
        return st.session_state.fa_step2_form

    # 从旧 fa_section_data 兜底迁移（如果用户在 Step 1 后回头用过 legacy 路径）
    legacy = st.session_state.get("fa_section_data") or {}
    legacy_header = legacy.get("header") or {}

    form = {
        "basic": {
            "name": legacy_header.get("name", ""),
            "gender": "",
            "phone": legacy_header.get("contact", {}).get("phone", ""),
            "email": legacy_header.get("contact", {}).get("email", ""),
            "location": legacy_header.get("location", ""),
            "target_role": (
                (st.session_state.get("fa_jd_structured") or {}).get("title")
                or st.session_state.get("fa_position") or ""
            ),
            "birth_year": "",
        },
        "education": _seed_education(legacy.get("education")),
        "work": _seed_work(legacy.get("experience")),
        "projects": _seed_projects(legacy.get("projects")),
        "skills_text": ", ".join(legacy.get("skills") or []),
        "certifications_text": "",
        "languages_text": ", ".join(legacy.get("languages") or []),
        "portfolio": "",
    }
    st.session_state.fa_step2_form = form
    return form


def _seed_education(legacy_edu: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """从旧 education 列表迁移，否则 1 段空模板。"""
    if legacy_edu:
        return [dict(e) for e in legacy_edu]
    return [{
        "school": "", "degree": "", "major": "",
        "start_year": "", "end_year": "", "gpa": "",
    }]


def _seed_work(legacy_exp: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    if legacy_exp:
        return [dict(e) for e in legacy_exp]
    return [{
        "company": "", "title": "",
        "start_date": "", "end_date": "至今",
        "description": "", "achievements_text": "",
    }]


def _seed_projects(legacy_proj: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    if legacy_proj:
        return [dict(p) for p in legacy_proj]
    return []


def _render_step2_basic(basic: Dict[str, str]) -> None:
    c1, c2, c3 = st.columns(3)
    with c1:
        basic["name"] = st.text_input(
            "姓名 *", value=basic.get("name", ""), key="fa_step2_basic_name"
        )
        basic["gender"] = st.text_input(
            "性别（可选）", value=basic.get("gender", ""), key="fa_step2_basic_gender"
        )
    with c2:
        basic["phone"] = st.text_input(
            "手机 *", value=basic.get("phone", ""), key="fa_step2_basic_phone"
        )
        basic["email"] = st.text_input(
            "邮箱 *", value=basic.get("email", ""), key="fa_step2_basic_email"
        )
    with c3:
        basic["location"] = st.text_input(
            "现居地", value=basic.get("location", ""), key="fa_step2_basic_loc"
        )
        basic["birth_year"] = st.text_input(
            "出生年（可选）", value=basic.get("birth_year", ""), key="fa_step2_basic_byear"
        )
    basic["target_role"] = st.text_input(
        "求职意向（与 JD 目标岗位）",
        value=basic.get("target_role", ""),
        key="fa_step2_basic_target",
    )


def _render_step2_education_list(form: Dict[str, Any]) -> None:
    items = form["education"]
    for idx, edu in enumerate(items):
        with st.container(border=True):
            c1, c2, c3, c4, c_del = st.columns([3, 2, 2, 1, 1])
            with c1:
                edu["school"] = st.text_input(
                    "学校 *", value=edu.get("school", ""), key=f"fa_s2_edu_school_{idx}"
                )
            with c2:
                edu["degree"] = st.text_input(
                    "学历 *", value=edu.get("degree", ""),
                    placeholder="本科/硕士/博士",
                    key=f"fa_s2_edu_degree_{idx}",
                )
            with c3:
                edu["major"] = st.text_input(
                    "专业", value=edu.get("major", ""), key=f"fa_s2_edu_major_{idx}"
                )
            with c4:
                edu["start_year"] = st.text_input(
                    "入学", value=edu.get("start_year", ""),
                    placeholder="2020",
                    key=f"fa_s2_edu_start_{idx}",
                )
            with c_del:
                if len(items) > 1 and st.button("✕", key=f"fa_s2_edu_del_{idx}"):
                    items.pop(idx)
                    st.rerun()
            c5, c6, _ = st.columns([3, 2, 5])
            with c5:
                edu["end_year"] = st.text_input(
                    "毕业", value=edu.get("end_year", ""),
                    placeholder="2024",
                    key=f"fa_s2_edu_end_{idx}",
                )
            with c6:
                edu["gpa"] = st.text_input(
                    "GPA（可选）", value=edu.get("gpa", ""),
                    key=f"fa_s2_edu_gpa_{idx}",
                )
    if st.button("+ 添加教育经历", key="fa_s2_edu_add"):
        items.append({
            "school": "", "degree": "", "major": "",
            "start_year": "", "end_year": "", "gpa": "",
        })
        st.rerun()


def _render_step2_work_list(form: Dict[str, Any]) -> None:
    items = form["work"]
    for idx, w in enumerate(items):
        with st.container(border=True):
            c1, c2, c3, c4, c_del = st.columns([3, 3, 2, 2, 1])
            with c1:
                w["company"] = st.text_input(
                    "公司 *", value=w.get("company", ""), key=f"fa_s2_w_company_{idx}"
                )
            with c2:
                w["title"] = st.text_input(
                    "岗位 *", value=w.get("title", ""), key=f"fa_s2_w_title_{idx}"
                )
            with c3:
                w["start_date"] = st.text_input(
                    "起始", value=w.get("start_date", ""),
                    placeholder="2022.06",
                    key=f"fa_s2_w_start_{idx}",
                )
            with c4:
                w["end_date"] = st.text_input(
                    "结束", value=w.get("end_date", "至今"),
                    key=f"fa_s2_w_end_{idx}",
                )
            with c_del:
                if len(items) > 1 and st.button("✕", key=f"fa_s2_w_del_{idx}"):
                    items.pop(idx)
                    st.rerun()
            w["description"] = st.text_area(
                "工作描述（事实流水账，不美化）",
                value=w.get("description", ""),
                height=100,
                key=f"fa_s2_w_desc_{idx}",
            )
            w["achievements_text"] = st.text_area(
                "成果数据（每行一条，HR 最看重的数字）",
                value=w.get("achievements_text", ""),
                height=80,
                key=f"fa_s2_w_achv_{idx}",
                placeholder="促成 200 单成交\nGMV 120 万\n团队规模从 3 扩到 10",
            )
    if st.button("+ 添加工作经历", key="fa_s2_w_add"):
        items.append({
            "company": "", "title": "",
            "start_date": "", "end_date": "至今",
            "description": "", "achievements_text": "",
        })
        st.rerun()


def _render_step2_project_list(form: Dict[str, Any]) -> None:
    items = form["projects"]
    for idx, p in enumerate(items):
        with st.container(border=True):
            c1, c2, c3, c4, c_del = st.columns([3, 2, 2, 2, 1])
            with c1:
                p["name"] = st.text_input(
                    "项目名", value=p.get("name", ""), key=f"fa_s2_p_name_{idx}"
                )
            with c2:
                p["role"] = st.text_input(
                    "我的角色", value=p.get("role", ""), key=f"fa_s2_p_role_{idx}"
                )
            with c3:
                p["start_date"] = st.text_input(
                    "起始", value=p.get("start_date", ""),
                    key=f"fa_s2_p_start_{idx}",
                )
            with c4:
                p["end_date"] = st.text_input(
                    "结束", value=p.get("end_date", "至今"),
                    key=f"fa_s2_p_end_{idx}",
                )
            with c_del:
                if st.button("✕", key=f"fa_s2_p_del_{idx}"):
                    items.pop(idx)
                    st.rerun()
            p["description"] = st.text_area(
                "项目描述", value=p.get("description", ""),
                height=80, key=f"fa_s2_p_desc_{idx}",
            )
            p["contribution"] = st.text_area(
                "我的贡献", value=p.get("contribution", ""),
                height=80, key=f"fa_s2_p_contrib_{idx}",
            )
            p["achievements_text"] = st.text_area(
                "成果数据（每行一条）",
                value=p.get("achievements_text", ""),
                height=60, key=f"fa_s2_p_achv_{idx}",
            )
    if st.button("+ 添加项目经历", key="fa_s2_p_add"):
        items.append({
            "name": "", "role": "", "start_date": "", "end_date": "至今",
            "description": "", "contribution": "", "achievements_text": "",
        })
        st.rerun()


def _render_step2_optional(form: Dict[str, Any]) -> None:
    form["skills_text"] = st.text_area(
        "技能（用逗号或换行分隔）",
        value=form.get("skills_text", ""),
        height=80,
        key="fa_s2_skills",
        placeholder="Python, SQL, LLM, RAG, 产品设计",
    )
    form["certifications_text"] = st.text_input(
        "证书（可选）",
        value=form.get("certifications_text", ""),
        key="fa_s2_certs",
        placeholder="PMP, AWS 认证, CPA",
    )
    form["languages_text"] = st.text_input(
        "语言能力（用逗号分隔）",
        value=form.get("languages_text", ""),
        key="fa_s2_langs",
        placeholder="中文（母语）, 英语（CET-6）",
    )
    form["portfolio"] = st.text_input(
        "作品集 / GitHub 链接（可选）",
        value=form.get("portfolio", ""),
        key="fa_s2_portfolio",
    )


def _validate_step2_form(form: Dict[str, Any]) -> Optional[str]:
    """Step 2 必填校验。返回 None = OK，否则返回错误信息。"""
    basic = form.get("basic") or {}
    if not (basic.get("name") or "").strip():
        return "姓名为必填。"
    if not (basic.get("phone") or "").strip() and not (basic.get("email") or "").strip():
        return "手机和邮箱至少填写一项。"
    for idx, edu in enumerate(form.get("education") or []):
        if not (edu.get("school") or "").strip() or not (edu.get("degree") or "").strip():
            return f"教育经历第 {idx + 1} 段：学校 / 学历必填。"
    for idx, w in enumerate(form.get("work") or []):
        if not (w.get("company") or "").strip() or not (w.get("title") or "").strip():
            return f"工作经历第 {idx + 1} 段：公司 / 岗位必填。"
    return None


def step2_form_to_resume(form: Dict[str, Any]) -> Dict[str, Any]:
    """把 Step 2 表单数据转成下游（Step 3 改写器 / OnePageEstimator）能吃的简历 dict。

    字段对齐 models.resume.py:ResumeProfile + update_plan §1.1。
    """
    basic = form.get("basic") or {}
    return {
        "name": basic.get("name", ""),
        "phone": basic.get("phone", ""),
        "email": basic.get("email", ""),
        "location": basic.get("location", ""),
        "target_roles": [basic.get("target_role", "")] if basic.get("target_role") else [],
        "summary": "",
        "experience": [
            {
                "company": w.get("company", ""),
                "title": w.get("title", ""),
                "start_date": w.get("start_date", ""),
                "end_date": w.get("end_date", ""),
                "description": w.get("description", ""),
                "achievements": [
                    a.strip() for a in (w.get("achievements_text", "") or "").splitlines() if a.strip()
                ],
            }
            for w in (form.get("work") or [])
        ],
        "projects": [
            {
                "name": p.get("name", ""),
                "role": p.get("role", ""),
                "start_date": p.get("start_date", ""),
                "end_date": p.get("end_date", ""),
                "description": p.get("description", ""),
                "contribution": p.get("contribution", ""),
                "achievements": [
                    a.strip() for a in (p.get("achievements_text", "") or "").splitlines() if a.strip()
                ],
            }
            for p in (form.get("projects") or [])
        ],
        "education": [
            {k: edu.get(k, "") for k in ("school", "degree", "major", "start_year", "end_year", "gpa")}
            for edu in (form.get("education") or [])
        ],
        "skills": [s.strip() for s in (form.get("skills_text", "") or "").replace("\n", ",").split(",") if s.strip()],
        "certifications": [s.strip() for s in (form.get("certifications_text", "") or "").split(",") if s.strip()],
        "languages": [s.strip() for s in (form.get("languages_text", "") or "").split(",") if s.strip()],
        "portfolio": form.get("portfolio", ""),
    }


# v3 round-2 Step 3: 模式 A / B / auto 切换 + 调 round-1 ResumeRewriter
#
# 设计（update_plan §1.2 + §1.3）：
# - 模式 A 改写（基于原简历，不编造数据）
# - 模式 B 生成模板（无公司名/时间/学校，数字用区间）
# - auto 模式：InformationScorer 推荐 → A / A+B / B
# - 模式 B 输出用虚线框 + 警示色 + "[AI 模板生成]" 标注
# - 完成后 → fa_step=4（一页纸预览 + 瘦身向导）
def render_flow_a_step_3_rewrite() -> None:
    """v3 Step 3: 模式 A/B/auto 切换器 + 改写结果展示。"""
    form = st.session_state.get("fa_step2_form")
    jd = st.session_state.get("fa_jd_structured")
    if not form:
        st.warning("⚠️ 请先完成 Step 2 填写简历内容。")
        if st.button("返回 Step 2", key="fa_step3_back2"):
            st.session_state.fa_step = 2
            st.rerun()
        return
    if not jd:
        st.warning("⚠️ 请先完成 Step 1 选择目标 JD。")
        if st.button("返回 Step 1", key="fa_step3_back1"):
            st.session_state.fa_step = 1
            st.rerun()
        return

    st.markdown('<span class="step-pill">第 3 步</span>改写 / 生成', unsafe_allow_html=True)
    target = (jd or {}).get("title") or "（未选岗位）"
    st.caption(f"目标岗位：{target} — 选择改写模式，AI 会按你的原简历 + 目标 JD 改写。")

    # 上一步
    if st.button("← 返回 Step 2 改简历内容", key="fa_step3_back"):
        st.session_state.fa_step = 2
        st.rerun()

    resume = step2_form_to_resume(form)
    score = _score_resume(resume)
    auto_mode = score["recommended_mode"]
    st.info(
        f"📊 **信息量评估**：{score['total_score']:.0f}/100 → "
        f"auto 推荐 **模式 {auto_mode}**（{score['reason']}）"
    )

    # 模式选择
    mode_choice = st.radio(
        "改写模式",
        options=["auto", "A", "B"],
        format_func=lambda m: {
            "auto": f"auto（推荐 {auto_mode}）",
            "A": "模式 A — 基于原简历改写（不编造数据）",
            "B": "模式 B — AI 生成模板（不带公司名/时间）",
        }[m],
        index=0,
        horizontal=True,
        key="fa_step3_mode_choice",
    )

    # 已有改写结果时显示
    rewrites = st.session_state.get("fa_step3_rewrites")
    last_mode = st.session_state.get("fa_step3_mode")
    first_run = st.session_state.get("fa_step3_first_run", True)

    # P1-2：按钮文案随首次/重跑变化
    if first_run:
        run_label = "🚀 改写 / 生成"
        run_help = "首次跑改写（用上方 auto / A / B 选择）"
    else:
        target_mode = auto_mode if mode_choice == "auto" else mode_choice
        if last_mode and target_mode != last_mode:
            run_label = f"🔁 切换为 模式 {target_mode} 重跑"
            run_help = f"上次跑的是模式 {last_mode}，这次按你的选择切到 {target_mode} 重跑"
        else:
            run_label = f"🔁 用 模式 {target_mode} 重跑"
            run_help = f"上次已经跑过模式 {last_mode or target_mode}，按相同模式再跑一遍"

    col_run, col_next = st.columns([1, 1])
    with col_run:
        run_clicked = st.button(
            run_label,
            type="primary",
            key="fa_step3_run",
            help=run_help,
        )
    with col_next:
        next_disabled = not rewrites
        if st.button(
            "下一步：预览与导出 →", disabled=next_disabled, key="fa_step3_next",
        ):
            st.session_state.fa_step = 4
            st.rerun()

    if run_clicked:
        actual_mode = auto_mode if mode_choice == "auto" else mode_choice
        with st.spinner(
            f"模式 {actual_mode} 改写中…（约 5-15s）"
        ):
            try:
                from services.resume_rewriter import ResumeRewriter
                rewriter = ResumeRewriter(
                    llm_client=st.session_state.get("llm_client"),
                )
                result = run_async(rewriter.rewrite(
                    original=resume,
                    jd=jd,
                    mode="auto" if mode_choice == "auto" else mode_choice,
                ))
                st.session_state.fa_step3_rewrites = result.to_dict()
                st.session_state.fa_step3_mode = result.mode
                st.session_state.fa_step3_first_run = False  # P1-2：标记已跑过
                # 把改写结果合并成下游（Step 4/5）能吃的 final_resume
                st.session_state.fa_step3_final_resume = _compose_final_resume(
                    resume, result, form,
                )
                st.success(f"✅ 模式 {result.mode} 改写完成（{len(result.rewrites)} 段）")
            except Exception as exc:
                st.error(f"改写失败：{exc}")
                return

    if rewrites:
        _render_rewrite_results(rewrites)


def _score_resume(resume: Dict[str, Any]) -> Dict[str, Any]:
    """调 round-1 InformationScorer。LLM 客户端未配置时返回 0 分。"""
    try:
        from services.information_scorer import InformationScorer
        scorer = InformationScorer()
        score = scorer.score(resume)
        return {
            "total_score": float(getattr(score, "total_score", 0)),
            "recommended_mode": str(getattr(score, "recommended_mode", "B")),
            "reason": str(getattr(score, "reason", "无评分信息")),
        }
    except Exception:
        return {"total_score": 0.0, "recommended_mode": "B", "reason": "评分失败，默认 B"}


def _compose_final_resume(
    resume: Dict[str, Any], result: Any, form: Dict[str, Any],
) -> Dict[str, Any]:
    """把改写结果合并进简历 dict（下游 Step 4/5 用）。"""
    out = dict(resume)
    rewrites = result.rewrites if hasattr(result, "rewrites") else result.get("rewrites", [])
    # 模式 A：每段含 section / original / rewritten → 用 rewritten 替换
    # 模式 B：每段含 section / content → 用 content 当作追加段
    out["_rewrites"] = list(rewrites)
    out["_rewrite_mode"] = getattr(result, "mode", "A")
    return out


def _render_rewrite_results(rewrites_dict: Dict[str, Any]) -> None:
    """展示改写结果（模式 A 段 vs 模式 B 段视觉区分）。"""
    rewrites = rewrites_dict.get("rewrites") or []
    mode = rewrites_dict.get("mode", "A")
    warnings = rewrites_dict.get("warnings") or []
    needs_review = rewrites_dict.get("needs_user_review", False)

    if warnings:
        with st.expander(f"⚠️ 警告（{len(warnings)} 条）", expanded=False):
            for w in warnings:
                st.warning(f"· {w}")

    if needs_review:
        st.caption("📝 改写结果需要人工校对（每段都附改写理由）。")

    for i, rw in enumerate(rewrites):
        section = rw.get("section") or f"段 {i + 1}"
        original = rw.get("original") or ""
        rewritten = rw.get("rewritten") or rw.get("content") or ""
        reason = rw.get("rewrite_reason") or ""
        warn = rw.get("warning") or ""
        is_ai = bool(rw.get("is_ai_generated", False)) or mode == "B"

        if is_ai:
            # 模式 B：虚线框 + 警示色 + [AI 模板生成] 标注
            st.markdown(
                f'<div style="border:2px dashed #d97706;background:#fffbeb;'
                f'padding:12px;margin:8px 0;border-radius:6px;color:#92400e">'
                f'<strong>⚠️ [AI 模板生成] · {section}</strong><br/>'
                f'{rewritten}<br/>'
                f'<small>anchored_keywords: {rw.get("anchored_keywords") or "-"}</small>'
                f'<br/><em>AI 虚构，不带公司名/时间/学校，请结合自身情况填写</em>'
                f'</div>',
                unsafe_allow_html=True,
            )
        else:
            # 模式 A：原 vs 改写对比
            with st.expander(f"✏️ {section}", expanded=False):
                if original:
                    st.markdown("**原**")
                    st.markdown(f"> {original}")
                st.markdown("**改写**")
                st.markdown(rewritten)
                if reason:
                    st.caption(f"💡 改写理由：{reason}")
                if warn:
                    st.caption(f"⚠️ 风险：{warn}")


# v3 round-2 Step 4: 一页纸实时预览 + 瘦身向导
#
# 设计（update_plan §1.4 + §2.5）：
# - 调 round-1 OnePageEstimator 实时估算
# - 标黄低优先级段（GPA<3.0 / 短期实习 / 重复技能）
# - AI 瘦身建议（合并/删除/精简）
# - 用户点选后实时刷新
# - 完成后 → fa_step=5（导出）
def render_flow_a_step_4_preview() -> None:
    """v3 Step 4: 一页纸实时预览 + 瘦身向导。"""
    form = st.session_state.get("fa_step2_form")
    final = st.session_state.get("fa_step3_final_resume")
    jd = st.session_state.get("fa_jd_structured")
    if not form or not final:
        st.warning("⚠️ 请先完成 Step 1-3。")
        if st.button("返回 Step 3", key="fa_step4_back3"):
            st.session_state.fa_step = 3
            st.rerun()
        return

    st.markdown('<span class="step-pill">第 4 步</span>一页纸预览 + 瘦身', unsafe_allow_html=True)
    st.caption("实时估算总高度，超页时按建议精简。")

    # 上一步
    if st.button("← 返回 Step 3 改写", key="fa_step4_back"):
        st.session_state.fa_step = 3
        st.rerun()

    # 实时估算
    estimate = _estimate_resume(final)
    _render_one_page_estimate(estimate)

    # 预览（用 document_generator 的 jinja2 模板）
    if st.session_state.get("fa_step3_mode") == "B":
        st.caption("📌 模式 B 输出含 AI 模板生成标记")

    if st.button("下一步：导出 Word / PDF →", type="primary", key="fa_step4_next"):
        st.session_state.fa_step = 5
        st.rerun()


def _estimate_resume(resume: Dict[str, Any]) -> Any:
    """调 round-1 OnePageEstimator。"""
    try:
        from services.one_page_estimator import OnePageEstimator
        estimator = OnePageEstimator()
        return estimator.estimate(resume)
    except Exception as exc:
        # 估算失败不阻塞主流程，返回一个 fallback PageEstimate
        from services.one_page_estimator import PageEstimate
        return PageEstimate(
            total_mm=0.0, capacity_mm=265.0, total_lines=0, capacity_lines=55,
            overflow=False, overflow_segments=[], suggestions=[f"估算失败：{exc}"],
            segment_lines={},
        )


def _render_one_page_estimate(estimate: Any) -> None:
    """渲染一页纸预估：进度条 + 段行数 + 瘦身建议。"""
    total = float(getattr(estimate, "total_mm", 0.0))
    cap = float(getattr(estimate, "capacity_mm", 265.0))
    overflow = bool(getattr(estimate, "overflow", False))
    pct = min(1.0, total / cap) if cap > 0 else 0.0

    if overflow:
        st.error(f"⚠️ 超页：{total:.1f}mm / {cap}mm（已用 {pct * 100:.0f}%）")
    else:
        st.success(f"✓ 一页可容纳：{total:.1f}mm / {cap}mm（已用 {pct * 100:.0f}%）")
    st.progress(pct)

    seg_lines = getattr(estimate, "segment_lines", {}) or {}
    if seg_lines:
        with st.expander(f"段行数明细（共 {sum(seg_lines.values())} 行）", expanded=False):
            for k, v in seg_lines.items():
                st.write(f"- {k}: {v} 行")

    suggestions = list(getattr(estimate, "suggestions", []) or [])
    overflow_segments = list(getattr(estimate, "overflow_segments", []) or [])
    if suggestions:
        st.markdown("##### 瘦身建议")
        for s in suggestions:
            st.markdown(f"- 💡 {s}")
    if overflow_segments:
        st.warning(f"超页段：{', '.join(overflow_segments)}")


# v3 round-2 Step 5: Word / PDF 导出
#
# 设计（update_plan §1.4 + §2.8 + §3.1）：
# - 调 document_generator（Word + PDF 统一接口）
# - 严格一页：超页直接报错
# - 文件命名：{姓名}_{岗位}_{公司}.{ext}
# - 完成后 → reset flow_a（让用户开始新一轮）
def render_flow_a_step_5_export() -> None:
    """v3 Step 5: Word / PDF 导出。"""
    form = st.session_state.get("fa_step2_form")
    final = st.session_state.get("fa_step3_final_resume")
    jd = st.session_state.get("fa_jd_structured")
    if not form or not final:
        st.warning("⚠️ 请先完成 Step 1-4。")
        if st.button("返回 Step 4", key="fa_step5_back4"):
            st.session_state.fa_step = 4
            st.rerun()
        return

    st.markdown('<span class="step-pill">第 5 步</span>导出 Word / PDF', unsafe_allow_html=True)
    st.caption("文件名：{姓名}_{岗位}_{公司}.{ext}。超页会被拦截。")

    # 上一步
    if st.button("← 返回 Step 4 预览", key="fa_step5_back"):
        st.session_state.fa_step = 4
        st.rerun()

    # 模板选择
    template = st.radio(
        "Word 模板",
        options=["conservative", "modern"],
        format_func=lambda t: {"conservative": "保守（经典灰）", "modern": "现代（蓝色头部栏）"}[t],
        horizontal=True,
        key="fa_step5_template",
    )

    # 估算 + 严格一页检查
    estimate = _estimate_resume(final)
    if getattr(estimate, "overflow", False):
        st.error("⚠️ 当前简历超出一页纸，请先回 Step 4 瘦身。")
        if st.button("返回 Step 4 瘦身", key="fa_step5_overflow_back"):
            st.session_state.fa_step = 4
            st.rerun()
        return

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("导出 Word (.docx)", type="primary", key="fa_step5_docx"):
            _handle_export("docx", final, jd, template)
    with col2:
        if st.button("导出 PDF", type="primary", key="fa_step5_pdf"):
            _handle_export("pdf", final, jd, template)
    with col3:
        if st.button("导出两者", type="primary", key="fa_step5_both"):
            _handle_export("docx", final, jd, template)
            _handle_export("pdf", final, jd, template)

    # 重新开始
    st.divider()
    if st.button("🔄 重新开始（清空当前流程）", key="fa_step5_reset"):
        reset_flow_a_state()
        st.rerun()


def _handle_export(ext: str, resume: Any, jd: Any, template: str) -> None:
    """调 document_generator，渲染并展示下载按钮。

    P0-1 闭环：PDF 路径失败时降级到 HTML 下载 + 浏览器打印指引（不静默 st.error 拦死）。
    """
    try:
        from services.document_generator import DocumentGenerator
        gen = DocumentGenerator()
        method = gen.generate_word if ext == "docx" else gen.generate_pdf
        result = method(resume, jd=jd, template=template, strict_one_page=True)
        st.success(
            f"✅ {ext.upper()} 已生成：{result.filename}（{len(result.content)} bytes）"
        )
        st.download_button(
            label=f"下载 {result.filename}",
            data=result.content,
            file_name=result.filename,
            mime=result.mime_type,
            key=f"fa_step5_dl_{ext}_{len(result.content)}",
        )
    except Exception as exc:
        if ext == "pdf":
            # P0-1 闭环：PDF 失败（playwright 未装 / chromium 缺失） → 降级到 HTML + 浏览器打印
            _offer_html_fallback(resume, jd, template, error=str(exc))
        else:
            st.error(f"导出失败：{exc}")


def _offer_html_fallback(
    resume: Any, jd: Any, template: str, error: Optional[str] = None,
) -> None:
    """P0-1 闭环：PDF 不可用时给用户 HTML 下载 + 浏览器打印指引。

    触发条件：playwright headless chromium 不可用（CI / 镜像 / Windows 无 chromium 等）。
    不抛异常，不静默 st.error — 让用户仍能把简历导出去。
    """
    from services.document_generator import DocumentGenerator, suggest_filename
    gen = DocumentGenerator()
    resume_d = gen._to_dict(resume)
    jd_d = gen._to_dict(jd) if jd is not None else {}
    try:
        html_bytes = gen._render_html(resume_d, jd_d, template, for_pdf=True).encode("utf-8")
    except Exception as exc:
        st.error(f"HTML 渲染也失败（极端情况）：{exc}")
        return

    jd_title = jd_d.get("title", "岗位") if jd_d else "通用岗位"
    company = jd_d.get("company", "公司") if jd_d else "公司"
    html_name = suggest_filename(
        name=resume_d.get("name", "简历"),
        jd_title=jd_title,
        company=company,
        ext="html",
    )
    if error:
        st.warning(
            f"⚠️ PDF 渲染失败（{error}）→ 降级到 **HTML + 浏览器打印** 方案"
        )
    else:
        st.info("📄 提供 HTML 下载（浏览器打开后用 Ctrl/Cmd+P 另存为 PDF）")

    st.download_button(
        label=f"下载 {html_name}",
        data=html_bytes,
        file_name=html_name,
        mime="text/html",
        key=f"fa_step5_dl_html_{len(html_bytes)}",
    )
    with st.expander("💡 浏览器打印 PDF 步骤", expanded=True):
        st.markdown(
            "1. 用浏览器打开下载的 HTML 文件\n"
            "2. 按 **Ctrl/Cmd + P** 打开打印对话框\n"
            "3. 目标选 **另存为 PDF**\n"
            "4. 边距选 **最小**（保证一页纸）\n"
            "5. 缩放 100%，点保存\n"
        )


# v3 round-2: 旧 v2.1 flow_a 4 步逻辑（T5/T6/T7/T8 逐步替换为新 UI）
def render_flow_a_legacy_steps() -> None:
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

        _render_flow_a_paste_panel(flow_a)
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
        # 先把后台 PDF 线程结果同步进 session_state（纯同步，不阻塞、不 rerun）
        _poll_pdf_status()
        # 简历正文 + 下载按钮永远先渲染——PDF 只是锦上添花，绝不阻塞查看/下载。
        st.markdown(st.session_state.fa_resume_md)
        sk = st.session_state.fa_skeleton or {}
        # PR3 (M11): 改写依据 + 来源面板
        _render_flow_a_provenance_panel(sk)
        dl1, dl2, dl3, dl4, dl5 = st.columns(5)
        pdf_status = st.session_state.get("fa_pdf_status", "ready")
        pdf_bytes = st.session_state.get("fa_resume_pdf")
        pdf_ready = pdf_status == "ready" and pdf_bytes
        with dl1:
            if pdf_ready:
                st.download_button(
                    "下载 PDF",
                    pdf_bytes,
                    file_name=f"{st.session_state.fa_position}_简历.pdf",
                    mime="application/pdf",
                )
            elif pdf_status == "pending":
                st.button("PDF 生成中…", disabled=True, help="后台渲染中（2-5 秒），完成后自动可下载")
            else:
                if st.button("重新生成 PDF", help=st.session_state.get("fa_pdf_error") or "PDF 渲染失败，可重试"):
                    st.session_state.fa_pdf_status = None
                    st.session_state.fa_pdf_wait_ticks = 0
                    _PDF_RESULT.clear()
                    _kick_off_background_pdf(st.session_state.fa_resume_html)
                    st.rerun()
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

        # 简历已完整呈现在上方——最后再做 PDF 的有界轮询。
        # 每 1.5s 刷新一次读后台结果，最多 ~12s；超时就标记失败并停手，
        # 不再无限空转（旧实现把这段放在正文之前，PDF 卡住时用户永远看不到简历）。
        if st.session_state.get("fa_pdf_status") == "pending":
            ticks = st.session_state.get("fa_pdf_wait_ticks", 0)
            if ticks < 8:
                st.session_state.fa_pdf_wait_ticks = ticks + 1
                import time as _time
                _time.sleep(1.5)
                st.rerun()
            else:
                st.session_state.fa_pdf_status = "failed"
                st.session_state.fa_pdf_error = "PDF 后台渲染超时（>12s）。Markdown / HTML 已可下载，可点「重新生成 PDF」重试。"
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
        st.session_state.fa_pdf_wait_ticks = 0
        _PDF_RESULT.clear()

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
    """把后台线程结果同步到 session_state。纯同步，不 sleep、不 rerun。

    自动刷新的节奏由调用方（渲染简历之后）控制，确保简历正文永远先于
    PDF 轮询渲染，PDF 卡住也不会挡住用户查看/下载。
    """
    if st.session_state.get("fa_pdf_status") != "pending":
        return
    s = _PDF_RESULT.get("status")
    if s == "ready":
        pdf_bytes = _PDF_RESULT.get("bytes")
        if pdf_bytes:
            st.session_state.fa_resume_pdf = pdf_bytes
            st.session_state.fa_pdf_status = "ready"
        else:
            # html_to_pdf_safe 失败时返回 None——按失败处理，别让下载按钮拿到 None 崩溃
            st.session_state.fa_pdf_status = "failed"
            st.session_state.fa_pdf_error = "PDF 渲染返回空（可能缺少 playwright/chromium）"
    elif s == "failed":
        st.session_state.fa_pdf_error = _PDF_RESULT.get("error")
        st.session_state.fa_pdf_status = "failed"


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

        if st.button("✅ 确认并进入生成", type="primary"):
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
