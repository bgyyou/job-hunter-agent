#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M-v4-1 web_app 拆分 — 投递历史 / 我的简历：版本树 + 主简历切换 + 克隆 + 删除。

来源：web_app.py 原 render_resume_library() + _render_version_tree + _short_time。

Streamlit multipage 自动识别 → sidebar 出现 "📈 Application History" 入口。

注意：原函数名 render_resume_library（"我的简历"），业务上更接近"投递历史 / 简历管理"。
沿用 PRD 命名 → 08_📈_Application_History.py。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st  # noqa: E402

from web_app import (  # noqa: E402
    init_session_state,
    init_app_services,
    render_top_nav,
    current_user_id,
)

st.set_page_config(
    page_title="JobHunter · 我的简历 / 投递历史",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ---------------------------------------------------------------------------
# Private helpers（原文搬迁）
# ---------------------------------------------------------------------------


def _short_time(iso: Optional[str]) -> str:
    if not iso:
        return ""
    return iso.replace("T", " ")[:16]


def _render_version_tree(db, user_id: str, tree: Dict[str, Any]) -> None:
    """渲染单个版本树（含克隆 / 切换主 / 删除操作）。"""
    from services.audit_service import log_action
    from services.resume_library_service import (
        ResumeLibraryError,
        clone_resume,
        set_primary_resume,
    )

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
# render
# ---------------------------------------------------------------------------


def render_application_history() -> None:
    """「我的简历 / 投递历史」页：版本树管理 + 主简历切换 + 克隆新版本。"""
    from services.resume_library_service import (
        get_primary_resume,
        list_resume_versions,
        list_resumes_flat,
    )

    render_top_nav()
    st.header("我的简历")
    st.caption("管理你所有简历版本。切换「主简历」后，求职匹配 / 优化都会默认用它。")

    db = st.session_state.db
    if db is None:
        st.error("数据库未初始化。")
        return

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


def main() -> None:
    init_session_state()
    init_app_services()
    render_application_history()


if __name__ == "__main__":
    main()
