#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M-v4-1 web_app 拆分 — 模式选择页（Flow A vs Flow B 入口）。

来源：web_app.py 原 render_mode_select()。
Streamlit multipage 自动识别 → sidebar 出现 "🎯 Mode Select" 入口。
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st  # noqa: E402

from web_app import (  # noqa: E402
    init_session_state,
    init_app_services,
    render_top_nav,
    reset_flow_b_state,
)

st.set_page_config(
    page_title="JobHunter · 模式选择",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def main() -> None:
    """render_mode_select() 全文搬迁。"""
    init_session_state()
    init_app_services()
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


if __name__ == "__main__":
    main()
