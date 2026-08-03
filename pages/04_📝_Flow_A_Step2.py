#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M-v4-1 web_app 拆分 — Flow A 第 2 步：渐进式披露表单（基本 + 教育 + 工作 + 项目 + 技能）。

来源：web_app.py 原 render_flow_a_step_2_form() + _ensure_step2_form + _seed_education +
_seed_work + _seed_projects + _render_step2_basic + _render_step2_education_list +
_render_step2_work_list + _render_step2_project_list + _render_step2_optional +
_validate_step2_form + step2_form_to_resume。

Streamlit multipage 自动识别 → sidebar 出现 "📝 Flow A Step2" 入口。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st  # noqa: E402

from web_app import (  # noqa: E402
    init_session_state,
    init_app_services,
    render_top_nav,
    reset_flow_a_state,
    reset_flow_a_v3_step_state,
    _sync_flow_a_position_from_jd,
)

st.set_page_config(
    page_title="JobHunter · Flow A Step 2",
    page_icon="📝",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ---------------------------------------------------------------------------
# Step 2 表单相关 helpers（原文搬迁）
# ---------------------------------------------------------------------------


def _ensure_step2_form() -> Dict[str, Any]:
    """确保 fa_step2_form 存在（首次进入 Step 2 初始化默认值）。"""
    if "fa_step2_form" in st.session_state and st.session_state.fa_step2_form:
        return st.session_state.fa_step2_form

    form = {
        "basic": {
            "name": "",
            "gender": "",
            "phone": "",
            "email": "",
            "location": "",
            "target_role": (
                (st.session_state.get("fa_jd_structured") or {}).get("title")
                or st.session_state.get("fa_position") or ""
            ),
            "birth_year": "",
        },
        "education": _seed_education(),
        "work": _seed_work(),
        "projects": _seed_projects(),
        "skills_text": "",
        "certifications_text": "",
        "languages_text": "",
        "portfolio": "",
    }
    st.session_state.fa_step2_form = form
    return form


def _seed_education() -> List[Dict[str, Any]]:
    return [{
        "school": "", "degree": "", "major": "",
        "start_year": "", "end_year": "", "gpa": "",
    }]


def _seed_work() -> List[Dict[str, Any]]:
    return [{
        "company": "", "title": "",
        "start_date": "", "end_date": "至今",
        "description": "", "achievements_text": "",
    }]


def _seed_projects() -> List[Dict[str, Any]]:
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
    """把 Step 2 表单数据转成下游（Step 3 改写器 / OnePageEstimator）能吃的简历 dict。"""
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


# ---------------------------------------------------------------------------
# Page entry
# ---------------------------------------------------------------------------


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


def main() -> None:
    init_session_state()
    init_app_services()
    _sync_flow_a_position_from_jd()
    render_top_nav()
    render_flow_a_step_2_form()


if __name__ == "__main__":
    main()
