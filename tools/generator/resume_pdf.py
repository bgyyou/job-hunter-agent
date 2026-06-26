# -*- coding: utf-8 -*-
"""把简历 HTML 转 PDF，用 playwright headless chromium。

Streamlit 非 async 上下文，用 sync API。A4 优化排版已由 resume_generator.to_html 处理。
"""
from __future__ import annotations

from loguru import logger


def html_to_pdf(html_str: str) -> bytes:
    """把完整 HTML 字符串渲染成 PDF bytes。

    用 data URL 加载，避免临时文件。headless chromium 启动约 1-2 秒，
    PDF 生成约 1-3 秒，总体 2-5 秒。失败抛异常，调用方决定降级行为。
    """
    from playwright.sync_api import sync_playwright
    import base64

    data_url = "data:text/html;base64," + base64.b64encode(html_str.encode("utf-8")).decode("ascii")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            context = browser.new_context()
            page = context.new_page()
            page.goto(data_url, wait_until="networkidle", timeout=15000)
            pdf_bytes = page.pdf(format="A4", print_background=True, margin={"top": "12mm", "bottom": "12mm", "left": "12mm", "right": "12mm"})
            return pdf_bytes
        finally:
            browser.close()


def html_to_pdf_safe(html_str: str) -> bytes | None:
    """安全版：失败记日志返回 None，不抛异常。"""
    try:
        return html_to_pdf(html_str)
    except Exception as exc:
        logger.warning(f"html_to_pdf failed: {exc}")
        return None
