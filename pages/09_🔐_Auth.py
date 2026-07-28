#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M-v4-1 web_app 拆分 — 登录 / 注册页。

来源：web_app.py 原 render_auth_page()。

Streamlit multipage 自动识别 → sidebar 出现 "🔐 Auth" 入口。
未登录态访问任何业务页面时由 web_app.py 路由分发自动 redirect 到此页。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st  # noqa: E402
from loguru import logger  # noqa: E402

from web_app import (  # noqa: E402
    init_session_state,
    init_app_services,
    _auth_service,
    _apply_login_session,
)
from services.auth_service import AuthError  # noqa: E402

st.set_page_config(
    page_title="JobHunter · 登录",
    page_icon="🔐",
    layout="wide",
    initial_sidebar_state="collapsed",
)


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


def main() -> None:
    init_session_state()
    init_app_services()
    render_auth_page()


if __name__ == "__main__":
    main()
