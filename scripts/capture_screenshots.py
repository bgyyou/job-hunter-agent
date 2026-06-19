"""一次性截 README 用截图。

用法：python scripts/capture_screenshots.py
- 截 (a) setup wizard（临时挪走 .env，跑一个独立 streamlit 实例）
- 截 (b) 主界面（恢复 .env）
- 输出到 docs/screenshots/
"""
from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
ENV_HIDE = ROOT / ".env.hidden_for_screenshot"
OUT = ROOT / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_for_port(port: int, timeout: float = 30) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def _start_streamlit(env_overrides: dict[str, str], port: int):
    env = os.environ.copy()
    env.update(env_overrides)
    env["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    env["STREAMLIT_SERVER_HEADLESS"] = "true"
    env["STREAMLIT_SERVER_PORT"] = str(port)
    env["STREAMLIT_SERVER_ADDRESS"] = "127.0.0.1"
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(ROOT / "web_app.py"),
         "--server.headless=true", f"--server.port={port}",
         "--server.address=127.0.0.1",
         "--browser.gatherUsageStats=false"],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


async def _shoot(url: str, out: Path, wait_extra: float = 3.0):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await ctx.new_page()
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(int(wait_extra * 1000))
        await page.screenshot(path=str(out), full_page=True)
        await browser.close()
    print(f"saved {out.relative_to(ROOT)}")


async def capture_wizard():
    if ENV.exists():
        shutil.move(str(ENV), str(ENV_HIDE))
    try:
        port = _free_port()
        # 强制 placeholder 让 wizard 触发
        proc = _start_streamlit({"VOLCANO_API_KEY": "your_api_key_here"}, port)
        try:
            ok = _wait_for_port(port, timeout=30)
            if not ok:
                print("streamlit failed to start (wizard)")
                return
            await _shoot(f"http://127.0.0.1:{port}", OUT / "01_setup_wizard.png", wait_extra=4.0)
        finally:
            proc.terminate()
            proc.wait(timeout=10)
    finally:
        if ENV_HIDE.exists():
            shutil.move(str(ENV_HIDE), str(ENV))


async def capture_main():
    port = _free_port()
    proc = _start_streamlit({}, port)
    try:
        ok = _wait_for_port(port, timeout=30)
        if not ok:
            print("streamlit failed to start (main)")
            return
        await _shoot(f"http://127.0.0.1:{port}", OUT / "02_main_ui.png", wait_extra=6.0)
    finally:
        proc.terminate()
        proc.wait(timeout=10)


async def main():
    print("[1/2] capturing setup wizard...")
    await capture_wizard()
    print("[2/2] capturing main UI...")
    await capture_main()


if __name__ == "__main__":
    asyncio.run(main())
