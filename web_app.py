#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Job Hunter product UI (Streamlit)."""
from __future__ import annotations

import asyncio
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

st.set_page_config(
    page_title="JobHunter",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
<style>
    .block-container { padding-top: 2rem; padding-bottom: 3rem; max-width: 1180px; }
    .hero-title { font-size: 3.3rem; line-height: 1.05; font-weight: 800; letter-spacing: -0.04em; color: #111827; }
    .hero-subtitle { font-size: 1.15rem; color: #475569; line-height: 1.8; margin: 1rem 0 1.5rem 0; }
    .muted { color: #64748b; }
    .product-card { border: 1px solid #e5e7eb; border-radius: 22px; padding: 1.4rem; background: #ffffff; box-shadow: 0 18px 45px rgba(15, 23, 42, 0.06); }
    .soft-card { border: 1px solid #e2e8f0; border-radius: 18px; padding: 1.25rem; background: #f8fafc; }
    .choice-card { border: 1px solid #e5e7eb; border-radius: 24px; padding: 1.6rem; background: #ffffff; min-height: 260px; }
    .before-card { border-left: 4px solid #ef4444; padding: 1rem; background: #fef2f2; border-radius: 14px; color: #7f1d1d; }
    .after-card { border-left: 4px solid #10b981; padding: 1rem; background: #ecfdf5; border-radius: 14px; color: #064e3b; }
    .step-pill { display:inline-block; padding: .35rem .7rem; border-radius: 999px; background:#eef2ff; color:#3730a3; font-size:.85rem; font-weight:600; margin-right:.4rem; }
    .public-badge { display:inline-block; padding:.2rem .55rem; border-radius:999px; background:#eff6ff; color:#1d4ed8; font-size:.78rem; }
    .private-badge { display:inline-block; padding:.2rem .55rem; border-radius:999px; background:#ecfdf5; color:#047857; font-size:.78rem; }
    div[data-testid="stSidebar"] { display: none; }
</style>
""",
    unsafe_allow_html=True,
)


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
        "auth_user": None,
        "auth_user_id": None,
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
        st.markdown("### JobHunter")
        st.caption(f"当前账号：{current_user_label()}")
    with jd_col:
        if st.button("JD库", use_container_width=True):
            st.session_state.app_route = "jd_library"
            st.rerun()
    with home_col:
        if st.button("首页", use_container_width=True):
            st.session_state.app_route = "mode_select"
            st.rerun()
    with logout_col:
        if st.button("退出", use_container_width=True):
            st.session_state.auth_user = None
            st.session_state.auth_user_id = None
            st.session_state.app_route = "landing"
            st.rerun()
    st.divider()


# ---------------------------------------------------------------------------
# Landing / mode select
# ---------------------------------------------------------------------------


def render_landing() -> None:
    hero_left, hero_right = st.columns([1.1, 0.9], gap="large")
    with hero_left:
        st.markdown('<div class="hero-title">把你的经历，改写成目标岗位想看的简历</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="hero-subtitle">基于真实 JD 库，自动分析差距、重写表达、生成定制简历和 Cover Letter。</div>',
            unsafe_allow_html=True,
        )
        cta_col, hint_col = st.columns([1, 2])
        with cta_col:
            if st.button("马上开始", type="primary", use_container_width=True):
                render_auth_dialog()
        with hint_col:
            st.caption("从 0 生成简历，或上传已有简历做岗位定制优化。")
        st.markdown(" ")
        v1, v2, v3 = st.columns(3)
        v1.metric("JD 召回", "RAG")
        v2.metric("双流程", "生成 / 优化")
        v3.metric("输出", "简历 + Cover Letter")

    with hero_right:
        st.markdown('<div class="product-card">', unsafe_allow_html=True)
        st.markdown("#### 简历优化示例")
        st.markdown('<div class="before-card"><b>原始表达</b><br/>负责产品需求分析，参与 AI 工具设计。</div>', unsafe_allow_html=True)
        st.markdown(" ")
        st.markdown('<div class="after-card"><b>优化后</b><br/>围绕 AI 搜索场景完成 12 个客户访谈与竞品拆解，定义 MVP 范围并推动 RAG 问答体验上线。</div>', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    st.divider()
    st.markdown("### 简历修改案例")
    cases = [
        ("项目经历太泛", "参与多智能体系统开发", "设计 Agent 协作链路与缓存策略，推动求职匹配流程从手工筛选转为自动化推荐。"),
        ("技能列表堆砌", "Python、SQL、LLM", "将 Python/SQL/LLM 落到 RAG 检索、Prompt 链路、质量评估等岗位相关场景。"),
        ("成果不够岗位化", "提升效率", "用目标 JD 的高频能力词重写成果：检索召回、用户转化、自动化运营、跨团队落地。"),
    ]
    cols = st.columns(3)
    for col, (title, before, after) in zip(cols, cases):
        with col:
            st.markdown('<div class="soft-card">', unsafe_allow_html=True)
            st.markdown(f"#### {title}")
            st.markdown(f"**Before**  \n{before}")
            st.markdown(f"**After**  \n{after}")
            st.markdown("</div>", unsafe_allow_html=True)


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

    collect_sections = [s for s in SECTIONS if not s.get("derived")]
    total_sections = len(SECTIONS)

    if not st.session_state.fa_position:
        st.markdown("### 第 1 步：选择目标岗位")
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

        if st.button("确定，开始对话", type="primary", disabled=position == "(请选择)" or not positions):
            st.session_state.fa_industry = industry
            st.session_state.fa_function = function
            st.session_state.fa_position = position
            st.session_state.fa_section_index = 0
            st.session_state.fa_section_data = {}
            st.session_state.fa_section_messages = {}
            st.session_state.fa_section_done = []
            st.session_state.fa_section_skipped = []
            st.rerun()
        return

    if st.session_state.fa_section_index < len(collect_sections):
        section = collect_sections[st.session_state.fa_section_index]
        section_key = section["key"]
        finished = len(st.session_state.fa_section_done) + len(st.session_state.fa_section_skipped)
        st.progress(finished / total_sections, text=f"进度 {finished}/{total_sections}")
        st.markdown(f"### 第 2 步：采集 {section['name']}")
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
    st.markdown("### 第 3 步：生成简历")
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
            rows = list_visible_jds(st.session_state.db, st.session_state.auth_user_id, limit=100)
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

    rows = list_visible_jds(
        st.session_state.db,
        user_id,
        search=search or None,
        source=None if source == "全部" else source,
        limit=100,
    )
    st.metric("可见 JD", len(rows))

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

if not st.session_state.auth_user:
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
