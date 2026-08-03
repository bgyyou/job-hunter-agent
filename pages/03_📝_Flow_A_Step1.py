#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M-v4-1 web_app 拆分 — Flow A 第 1 步：JD 输入（三选一）+ 校对 + 入库。

来源：web_app.py 原 render_flow_a_step_1_jd_input() + _render_jd_rag_panel +
_render_jd_text_panel + _render_jd_image_panel + _render_jd_review_form +
_jd_to_dict + _sync_flow_a_position_from_jd。

Streamlit multipage 自动识别 → sidebar 出现 "📝 Flow A Step1" 入口。

注意：render_flow_a_step_1_jd_input 是 render_flow_a dispatcher 的 fa_step==1 分支；
dispatcher 本身（render_flow_a）留在 web_app.py。
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st  # noqa: E402

from web_app import (  # noqa: E402
    init_session_state,
    init_app_services,
    render_top_nav,
    run_async,
    _save_flow_a_draft,
    current_user_id,
)
from tools import taxonomy  # noqa: E402
from services.text_limits import MAX_USER_TEXT_CHARS, clamp_user_text  # noqa: E402

st.set_page_config(
    page_title="JobHunter · Flow A Step 1",
    page_icon="📝",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ---------------------------------------------------------------------------
# Private helpers（render_flow_a_step_1_jd_input 的全部私有 helper）
# ---------------------------------------------------------------------------


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
        # P0-008 同根因：不用 "default" 兜底 user_id，否则解析出的 JD 会落到共享账号下。
        d["user_id"] = getattr(jd_obj, "user_id", None) or current_user_id()
        return d
    if hasattr(jd_obj, "__dict__"):
        return vars(jd_obj)
    return {}


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
        max_chars=MAX_USER_TEXT_CHARS,
        key="fa_step1_text_input",
        placeholder="示例：\n字节跳动 / AI 产品经理\n岗位职责：\n1. 负责 LLM 应用的需求分析…\n2. …\n任职要求：\n1. 本科及以上…\n",
    )
    # 同步到 session_state 以便提交按钮读取最新值
    st.session_state.fa_jd_text_input = text
    if st.button("解析", type="primary", disabled=not text.strip(), key="fa_step1_text_run"):
        text, truncated = clamp_user_text(text)
        if truncated:
            st.warning(f"JD 超过 {MAX_USER_TEXT_CHARS} 字符，已截断后解析。建议只粘贴职责/要求正文。")
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

    OCR 不可信 → 强制 needs_user_review=True，强制走校对界面。
    """
    uploaded = st.file_uploader(
        "上传 JD 截图（PNG / JPG）",
        type=["png", "jpg", "jpeg", "webp", "bmp"],
        key="fa_step1_image_upload",
    )
    if uploaded is not None:
        # 保存到临时路径（ImageJDParser.parse 接文件路径）
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
            max_chars=MAX_USER_TEXT_CHARS,
            key="fa_step1_rev_resp",
        )
        requirements = st.text_area(
            "要求（每行一条）",
            value="\n".join(jd.get("requirements") or []),
            height=120,
            max_chars=MAX_USER_TEXT_CHARS,
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


# ---------------------------------------------------------------------------
# Page entry
# ---------------------------------------------------------------------------


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


def main() -> None:
    """Streamlit multipage 入口：跑 init + 同步兼容 state + 调 render_flow_a_step_1_jd_input。"""
    init_session_state()
    init_app_services()
    _sync_flow_a_position_from_jd()
    render_top_nav()
    render_flow_a_step_1_jd_input()


if __name__ == "__main__":
    main()
