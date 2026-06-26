# -*- coding: utf-8 -*-
"""自动截图脚本：访问 Streamlit 各路由，截图到 docs/screenshots/。

依赖：playwright（pip install playwright; playwright install chromium）
Streamlit 必须在 localhost:8501 跑着。

用法：
    python tools/screenshot/capture_pages.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE = "http://localhost:8501"
OUT = Path(__file__).parent.parent.parent / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)


def shot(page, name: str, full_page: bool = True) -> None:
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=full_page)
    print(f"  saved {name}.png")


def wait(page, ms: int = 2000) -> None:
    page.wait_for_timeout(ms)


def goto(page, path: str, wait_text: str | None = None) -> None:
    """访问 path，等 wait_text 出现再返回。streamlit 的 networkidle 不靠谱，用文字等。"""
    page.goto(f"{BASE}{path}", wait_until="domcontentloaded", timeout=30000)
    if wait_text:
        try:
            page.get_by_text(wait_text, exact=False).first.wait_for(timeout=15000, state="visible")
        except PWTimeout:
            print(f"  warn: '{wait_text}' 没出现")
    wait(page, 1500)


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
        page = context.new_page()

        print("[1/9] landing")
        goto(page, "/", wait_text="JobHunter")
        shot(page, "01_landing")

        print("[2/9] mode_select")
        goto(page, "/?route=mode_select", wait_text="你今天想做什么")
        shot(page, "02_mode_select")

        print("[3/9] flow_a step 1 select")
        goto(page, "/?route=flow_a", wait_text="选择目标岗位")
        shot(page, "03_flow_a_step1_select")

        print("[4/9] flow_a step 2 form")
        goto(page, "/?route=flow_a&dev_step=basic_form", wait_text="个人信息")
        shot(page, "04_flow_a_step2_form")

        print("[5/9] flow_a step 3 chat")
        goto(page, "/?route=flow_a&dev_step=chat", wait_text="采集")
        try:
            page.wait_for_selector('[data-testid="stChatMessage"]', timeout=45000)
            wait(page, 4000)
        except PWTimeout:
            print("  warn: chat message 没出现")
        shot(page, "05_flow_a_step3_chat")

        print("[6/9] flow_b")
        goto(page, "/?route=flow_b", wait_text="上传并解析简历")
        shot(page, "06_flow_b")

        print("[7/9] jd_library")
        goto(page, "/?route=jd_library", wait_text="JD库")
        try:
            page.wait_for_selector('[data-testid="stExpander"]', timeout=10000)
        except PWTimeout:
            pass
        shot(page, "07_jd_library")

        print("[8/9] privacy")
        goto(page, "/?page=privacy", wait_text="隐私政策")
        shot(page, "08_privacy")

        print("[9/9] terms")
        goto(page, "/?page=terms", wait_text="服务条款")
        shot(page, "09_terms")

        browser.close()
        print(f"\nDone. {len(list(OUT.glob('0*.png')))} screenshots in {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
