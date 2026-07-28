#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M-v4-1 web_app 拆分 — Landing / privacy / terms 页。

来源：web_app.py 原 render_landing() + _render_landing_live_band()（+ live snapshot helpers）。
Streamlit multipage 自动识别 → sidebar 出现 "🏠 Landing" 入口。

入口：main()，由 streamlit run web_app.py 路由分发 或 sidebar multipage 触发。
共享 helpers 来自 web_app（init_session_state / init_app_services / _render_landing_live_band 等）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st  # noqa: E402

# 共享 helpers：init / live snapshot 不依赖 page 私有状态
from web_app import (  # noqa: E402
    init_session_state,
    init_app_services,
    _render_landing_live_band,
)

st.set_page_config(
    page_title="JobHunter · Landing",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def main() -> None:
    """render_landing() 全文搬迁（landing + privacy/terms 两条路径）。"""
    init_session_state()
    init_app_services()

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


if __name__ == "__main__":
    main()
