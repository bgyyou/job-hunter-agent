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

load_dotenv()

from agents.coordinator import CoordinatorAgent
from agents.resume_flow_a import ResumeFlowA, SECTIONS
from config.settings import settings
from database.backends.sqlite_backend import SqliteBackend
from database.classifier import Classifier
from services.auth_service import AuthError, AuthService
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
from services.pdf_ingestion_service import PdfIngestionService
from tools import taxonomy
from tools.generator.cover_letter_generator import CoverLetterGenerator
from tools.generator.resume_generator import ResumeGenerator
from tools.generator.resume_optimizer import ResumeOptimizer
from tools.jd_indexer import embed_and_store_jd_chunks
from tools.llm import OpenAICompatibleClient
from tools.resume_parser import ResumeParser
from tools.scraper.jd_analyzer_enhanced import JDAnalyzerEnhanced
from tools.scraper.scraper_manager import ScraperManager

settings.setup_logging()

LLM_COLLECT_SECTION_KEYS = {"experience", "projects"}

# 开发期跳过登录，上线前改 .env BYPASS_AUTH=false 或删除该变量
BYPASS_AUTH = os.environ.get("BYPASS_AUTH", "true").lower() not in {"false", "0", "no"}
DEV_USER = {
    "id": "dev-user",
    "name": "开发者",
    "email": "dev@local",
    "phone": None,
}

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


def init_session_state() -> None:
    defaults = {
        "app_route": "landing",
        "show_landing": False,
        "auth_user": DEV_USER if BYPASS_AUTH else None,
        "auth_user_id": DEV_USER["id"] if BYPASS_AUTH else None,
        "services_ready": False,
        "llm_init_error": None,
        "llm_client": None,
        "agent": None,
        "scraper_manager": None,
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
        "fa_messages": [],
        "fa_chat_done": False,
        "fa_resume_data": None,
        "fa_resume_md": None,
        "fa_resume_html": None,
        "fa_skeleton": None,
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
        st.session_state.scraper_manager = ScraperManager(llm_client=llm_client)
        st.session_state.services_ready = True
        st.session_state.llm_init_error = None
    except Exception as exc:
        st.session_state.services_ready = False
        st.session_state.llm_init_error = f"AI 服务初始化失败：{exc}"


def current_user_label() -> str:
    user = st.session_state.auth_user or {}
    return user.get("name") or user.get("email") or user.get("phone") or "用户"


def require_services() -> bool:
    if st.session_state.services_ready:
        return True
    st.warning(st.session_state.llm_init_error or "AI 服务暂不可用。")
    return False


def reset_flow_a_state() -> None:
    for key in [
        "fa_industry", "fa_function", "fa_position", "fa_resume_data",
        "fa_resume_md", "fa_resume_html", "fa_skeleton",
    ]:
        st.session_state[key] = None
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


# ---------------------------------------------------------------------------
# Auth UI
# ---------------------------------------------------------------------------


@st.dialog("登录 / 注册")
def render_auth_dialog() -> None:
    auth = AuthService(st.session_state.db)
    login_tab, register_tab = st.tabs(["登录", "注册"])

    with login_tab:
        with st.form("login_form"):
            identifier = st.text_input("邮箱或手机号")
            password = st.text_input("密码", type="password")
            submitted = st.form_submit_button("登录", type="primary")
        if submitted:
            try:
                user = auth.login_user(identifier=identifier, password=password)
                st.session_state.auth_user = user
                st.session_state.auth_user_id = user["id"]
                st.session_state.app_route = "mode_select"
                st.rerun()
            except AuthError as exc:
                st.error(str(exc))

    with register_tab:
        st.caption("微信登录、短信验证码、邮箱验证码会作为上线 provider 接入；当前先用本地账号跑通用户数据归属。")
        mode = st.radio("注册方式", ["邮箱", "手机号"], horizontal=True)
        with st.form("register_form"):
            name = st.text_input("昵称（可选）")
            email = st.text_input("邮箱") if mode == "邮箱" else None
            phone = st.text_input("手机号") if mode == "手机号" else None
            password = st.text_input("密码（至少 8 位）", type="password")
            submitted = st.form_submit_button("注册并登录", type="primary")
        if submitted:
            try:
                user = auth.register_user(email=email, phone=phone, password=password, name=name)
                st.session_state.auth_user = user
                st.session_state.auth_user_id = user["id"]
                st.session_state.app_route = "mode_select"
                st.rerun()
            except AuthError as exc:
                st.error(str(exc))


# ---------------------------------------------------------------------------
# Common navigation
# ---------------------------------------------------------------------------


def render_top_nav() -> None:
    left, spacer, jd_col, home_col, logout_col = st.columns([3, 3, 1, 1, 1])
    with left:
        st.markdown('<div class="topnav-title">JobHunter</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="topnav-account">当前账号：{current_user_label()}</div>', unsafe_allow_html=True)
    with jd_col:
        if st.button("JD库", use_container_width=True):
            st.session_state.app_route = "jd_library"
            st.rerun()
    with home_col:
        if st.button("首页", use_container_width=True):
            st.session_state.app_route = "mode_select"
            st.rerun()
    with logout_col:
        if BYPASS_AUTH:
            if st.button("返回落地页", use_container_width=True):
                st.session_state.show_landing = True
                st.rerun()
        else:
            if st.button("退出", use_container_width=True):
                st.session_state.auth_user = None
                st.session_state.auth_user_id = None
                st.session_state.app_route = "landing"
                st.rerun()
    st.markdown('<hr class="topnav-divider">', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Landing / mode select
# ---------------------------------------------------------------------------


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

    if st.session_state.get("pending_auth_dialog"):
        st.session_state.pending_auth_dialog = False
        render_auth_dialog()
        return

    if st.query_params.get("auth") == "1":
        if BYPASS_AUTH:
            st.session_state.auth_user = DEV_USER
            st.session_state.auth_user_id = DEV_USER["id"]
            st.session_state.app_route = "mode_select"
            st.query_params.pop("auth", None)
            st.rerun()
            return
        st.session_state.pending_auth_dialog = True
        st.query_params.pop("auth", None)
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


def render_mode_select() -> None:
    render_top_nav()
    st.markdown("## 你今天想做什么？")
    st.caption("两条流程完全隔离：从 0 生成不会混进已有简历优化；修改已有简历也不会跳到对话采集。")

    col_a, col_b = st.columns(2, gap="large")
    with col_a:
        st.markdown('<div class="choice-card">', unsafe_allow_html=True)
        st.markdown("### 从0生成简历")
        st.write("适合没有现成简历，或想按目标岗位重新组织经历的人。")
        st.markdown("- 选择行业 / 职能 / 岗位\n- 和 Agent 多轮对话采集经历\n- 基于 JD 库生成岗位化简历")
        if st.button("开始生成", type="primary", use_container_width=True):
            reset_flow_a_state()
            st.session_state.app_route = "flow_a"
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    with col_b:
        st.markdown('<div class="choice-card">', unsafe_allow_html=True)
        st.markdown("### 修改已有简历")
        st.write("适合已有简历，需要针对某个 JD 做匹配分析和定制改写。")
        st.markdown("- 上传简历和 JD\n- 分析匹配度与差距\n- 生成优化简历和 Cover Letter")
        if st.button("开始优化", type="primary", use_container_width=True):
            reset_flow_b_state()
            st.session_state.app_route = "flow_b"
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Flow A
# ---------------------------------------------------------------------------


def render_flow_a() -> None:
    render_top_nav()
    st.header("从0生成简历")
    st.caption("先确定目标岗位，再按 section 逐步采集信息。")

    if not require_services():
        return

    collect_sections = [s for s in SECTIONS if not s.get("derived") and s["key"] in LLM_COLLECT_SECTION_KEYS]
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
                st.rerun()
        return

    if st.session_state.fa_section_index < len(collect_sections):
        section = collect_sections[st.session_state.fa_section_index]
        section_key = section["key"]
        finished = 1 + len(st.session_state.fa_section_done) + len(st.session_state.fa_section_skipped)
        st.progress(finished / total_sections, text=f"进度 {finished}/{total_sections}")
        st.markdown(f'<span class="step-pill">第 3 步</span>采集 {section["name"]}', unsafe_allow_html=True)
        st.caption(f"目标：{st.session_state.fa_industry} / {st.session_state.fa_position}")

        if st.button("重新选择岗位"):
            reset_flow_a_state()
            st.rerun()

        sec_msgs = st.session_state.fa_section_messages.setdefault(section_key, [])
        for msg in sec_msgs:
            with st.chat_message("user" if msg["role"] == "user" else "assistant"):
                st.markdown(msg["content"])

        needs_assistant_turn = not sec_msgs or sec_msgs[-1]["role"] == "user"
        if needs_assistant_turn:
            with st.spinner(f"Agent 正在准备 {section['name']} 的问题..."):
                try:
                    flow_a = ResumeFlowA(st.session_state.llm_client, db=st.session_state.db)
                    msgs_for_llm = sec_msgs if sec_msgs else [{"role": "user", "content": f"开始采集{section['name']}吧。"}]
                    reply = run_async(flow_a.chat_section(
                        section_key=section_key,
                        messages=msgs_for_llm,
                        collected_so_far=st.session_state.fa_section_data,
                        industry=st.session_state.fa_industry,
                        position=st.session_state.fa_position,
                    ))
                    if not sec_msgs:
                        sec_msgs.append({"role": "user", "content": f"开始采集{section['name']}吧。"})
                    sec_msgs.append({"role": "assistant", "content": reply["message"]})

                    if reply["type"] == "section_skipped":
                        st.session_state.fa_section_skipped.append(section_key)
                        st.session_state.fa_section_index += 1
                    elif reply["type"] == "section_done":
                        extracted = run_async(flow_a.extract_section(section_key, sec_msgs))
                        st.session_state.fa_section_data[section_key] = extracted
                        st.session_state.fa_section_done.append(section_key)
                        st.session_state.fa_section_index += 1
                    st.rerun()
                except Exception as exc:
                    st.error(f"AI 响应失败：{exc}")

        user_input = st.chat_input(f"回复关于「{section['name']}」的问题...")
        if user_input:
            sec_msgs.append({"role": "user", "content": user_input})
            st.rerun()

        b1, b2, _ = st.columns(3)
        with b1:
            if section.get("skippable") and st.button(f"跳过 {section['name']}"):
                st.session_state.fa_section_skipped.append(section_key)
                st.session_state.fa_section_index += 1
                st.rerun()
        with b2:
            if st.button("完成本节，进入下一节"):
                try:
                    flow_a = ResumeFlowA(st.session_state.llm_client, db=st.session_state.db)
                    if sec_msgs:
                        extracted = run_async(flow_a.extract_section(section_key, sec_msgs))
                        st.session_state.fa_section_data[section_key] = extracted
                except Exception as exc:
                    st.warning(f"提取本节数据时出错（继续推进）：{exc}")
                st.session_state.fa_section_done.append(section_key)
                st.session_state.fa_section_index += 1
                st.rerun()
        return

    st.progress(1.0, text=f"进度 {total_sections}/{total_sections} ✓")
    st.markdown('<span class="step-pill">第 4 步</span>生成简历', unsafe_allow_html=True)
    if st.session_state.fa_resume_md is None:
        with st.spinner("正在检索 JD 库、派生总结与核心能力、生成简历..."):
            try:
                flow_a = ResumeFlowA(st.session_state.llm_client, db=st.session_state.db)
                collected = st.session_state.fa_section_data or {}
                skeleton = run_async(flow_a.build_skeleton(st.session_state.fa_position, st.session_state.fa_industry))
                derived = run_async(flow_a.derive_summary_and_competencies(
                    collected,
                    industry=st.session_state.fa_industry,
                    position=st.session_state.fa_position,
                    skeleton_text=skeleton.get("text", ""),
                ))
                skills_val = collected.get("skills")
                if isinstance(skills_val, dict):
                    skills_val = skills_val.get("skills", [])
                languages_val = collected.get("languages")
                if isinstance(languages_val, dict):
                    languages_val = languages_val.get("languages", [])
                raw_resume = {
                    "header": collected.get("header", {}),
                    "summary": derived.get("summary", ""),
                    "core_competencies": derived.get("core_competencies", []),
                    "education": collected.get("education", []) or [],
                    "experience": collected.get("experience", []) or [],
                    "projects": collected.get("projects", []) or [],
                    "skills": skills_val or [],
                    "languages": languages_val or [],
                }
                final_data = flow_a._normalize_resume_shape(raw_resume)
                st.session_state.fa_resume_data = final_data
                st.session_state.fa_skeleton = skeleton
                st.session_state.fa_resume_md = flow_a.to_markdown(final_data)
                st.session_state.fa_resume_html = flow_a.to_html(final_data)
                st.success("简历生成成功！")
            except Exception as exc:
                st.error(f"生成失败：{exc}")

    if st.session_state.fa_resume_md:
        st.markdown(st.session_state.fa_resume_md)
        sk = st.session_state.fa_skeleton or {}
        st.caption(f"本轮 RAG 命中 {sk.get('n_chunks', 0)} 条 JD chunk。")
        dl1, dl2, dl3, dl4 = st.columns(4)
        with dl1:
            st.download_button("下载 Markdown", st.session_state.fa_resume_md, file_name=f"{st.session_state.fa_position}_简历.md", mime="text/markdown")
        with dl2:
            st.download_button("下载 HTML", st.session_state.fa_resume_html, file_name=f"{st.session_state.fa_position}_简历.html", mime="text/html")
        with dl3:
            if st.button("保存到数据库"):
                rd = st.session_state.fa_resume_data
                resume_payload = {
                    "user_id": st.session_state.auth_user_id,
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
                st.success(f"已保存，resume_id={resume_id[:12]}...")
        with dl4:
            if st.button("重新开始"):
                reset_flow_a_state()
                st.rerun()


# ---------------------------------------------------------------------------
# Flow B
# ---------------------------------------------------------------------------


def resume_to_db_payload(resume_data: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    header = resume_data.get("header", {})
    contact = header.get("contact", {})
    return {
        "user_id": user_id,
        "name": header.get("name", resume_data.get("name", "")),
        "phone": contact.get("phone", resume_data.get("phone")),
        "email": contact.get("email", resume_data.get("email")),
        "summary": header.get("summary", resume_data.get("summary", "")),
        "skills": resume_data.get("skills", []),
        "education": resume_data.get("education", []),
        "projects": resume_data.get("projects", []),
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

    render_generation_toolbar()
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
                    resume_to_db_payload(resume_data, st.session_state.auth_user_id)
                )
                st.success("简历解析完成。")
        if st.session_state.resume_data:
            st.json(st.session_state.resume_data, expanded=False)

    with st.expander("2. 上传 / 选择目标 JD", expanded=st.session_state.resume_data is not None and st.session_state.jd_result is None):
        input_type = st.radio("JD 来源", ["粘贴 JD", "上传 PDF", "从 JD库选择", "职位 URL"], horizontal=True, key="fb_jd_input_type_radio")
        if input_type == "粘贴 JD":
            jd_text = st.text_area("粘贴目标 JD", height=220)
            if st.button("分析并保存 JD", disabled=not jd_text):
                with st.spinner("正在分析 JD..."):
                    analyzer = JDAnalyzerEnhanced(llm_client=st.session_state.llm_client)
                    jd_result = run_async(analyzer.parse_from_text(jd_text))
                    jd_payload = jd_to_db_payload(jd_text, jd_result, st.session_state.auth_user_id, source="manual")
                    jd_id = insert_user_jd(st.session_state.db, st.session_state.auth_user_id, jd_payload)
                    embed_and_store_jd_chunks(st.session_state.db, jd_id, jd_text, user_id=st.session_state.auth_user_id)
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
                        str(pdf_path), user_id=st.session_state.auth_user_id,
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
            total = count_visible_jds(st.session_state.db, st.session_state.auth_user_id, search=jd_search or None)
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
                st.session_state.auth_user_id,
                search=jd_search or None,
                limit=page_size,
                offset=(st.session_state.flow_b_jd_page - 1) * page_size,
            )
            options = {f"{r.get('title') or '未命名'} @ {r.get('company') or '未知公司'} ({r.get('source')})": r["id"] for r in rows}
            selected = st.selectbox("选择 JD", list(options.keys()) if options else ["JD库暂无内容"])
            if options and st.button("使用这个 JD"):
                jd = get_visible_jd(st.session_state.db, st.session_state.auth_user_id, options[selected])
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
                    jd_payload = jd_to_db_payload(raw_text, jd_result, st.session_state.auth_user_id, source="url")
                    jd_payload["url"] = jd_url
                    jd_id = insert_user_jd(st.session_state.db, st.session_state.auth_user_id, jd_payload)
                    embed_and_store_jd_chunks(st.session_state.db, jd_id, raw_text, user_id=st.session_state.auth_user_id)
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
                        "user_id": st.session_state.auth_user_id,
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
                    opt_ids = []
                    for rec in match_result.get("recommendations", []):
                        opt_ids.append(st.session_state.db.insert_optimization({
                            "user_id": st.session_state.auth_user_id,
                            "resume_id": st.session_state.resume_id,
                            "jd_id": st.session_state.jd_id,
                            "optimization_type": rec.get("type", "modify"),
                            "section": rec.get("section", ""),
                            "original_content": rec.get("original", ""),
                            "suggested_content": rec.get("suggestion", ""),
                            "reason": rec.get("reason", ""),
                        }))
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


def render_jd_library() -> None:
    render_top_nav()
    st.header("JD库")
    st.caption("这里保存你上传过的 JD，也能看到之前爬取的公共种子 JD。")

    user_id = st.session_state.auth_user_id
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
        with st.expander(f"{jd.get('title') or '未命名'} @ {jd.get('company') or '未知公司'}"):
            st.markdown(badge, unsafe_allow_html=True)
            st.caption(f"来源：{jd.get('source')} · 岗位标签：{jd.get('position_tag') or '未分类'}")
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
                        st.success("已删除。")
                        st.rerun()
                    except JdLibraryError as exc:
                        st.error(str(exc))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


init_session_state()
init_app_services()

if BYPASS_AUTH and st.session_state.get("show_landing"):
    st.session_state.show_landing = False
    render_landing()
elif not st.session_state.auth_user:
    render_landing()
elif st.session_state.app_route == "flow_a":
    render_flow_a()
elif st.session_state.app_route == "flow_b":
    render_flow_b()
elif st.session_state.app_route == "jd_library":
    render_jd_library()
else:
    st.session_state.app_route = "mode_select"
    render_mode_select()
