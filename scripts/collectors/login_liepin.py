#!/usr/bin/env python3
"""Liepin 登录助手。

v2.1 M6.B.3.2: 与 login_jobsdb.py 同款套路——开 Edge 浏览器让用户手动登录，
登录态保存到 data/browser_profiles/liepin/，之后 LiepinScraper 复用。

使用：
    python scripts/collectors/login_liepin.py
"""
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

import asyncio
from loguru import logger

from tools.scraper.liepin_scraper import LiepinScraper


async def main():
    print("=" * 60)
    print("Job Hunter - Liepin 登录助手")
    print("=" * 60)
    print()
    print("1. 即将打开 Edge 浏览器访问猎聘首页")
    print("2. 在浏览器中手动完成登录（扫码 / 账密均可）")
    print("3. 脚本每 5 秒检测一次登录态，登录成功自动关闭浏览器")
    print("4. 之后 LiepinScraper 会自动复用该 profile")
    print()

    async with LiepinScraper(headless=False) as scraper:
        await scraper.playwright_scraper.human_navigate("https://www.liepin.com/")
        await scraper.playwright_scraper.human_read_page(min_seconds=2.0, max_seconds=3.0)
        page = scraper.playwright_scraper.page
        logger.info("等待用户登录（轮询模式，最多 5 分钟，不刷新页面）…")

        # 轮询 60 次 × 5s = 最多 5 分钟
        # 关键：只查 DOM，不重 navigate，否则页面会被刷掉用户输入
        for i in range(60):
            await asyncio.sleep(5)
            try:
                logged_in = await scraper._is_logged_in_via_dom(page)
                if not logged_in:
                    body_text = await page.evaluate("() => document.body.innerText")
                    if (
                        "个人中心" in body_text
                        or "我的简历" in body_text
                        or "退出" in body_text
                    ):
                        logged_in = True
            except Exception as exc:
                logger.debug(f"check 第 {i+1} 次异常: {exc}")
                continue
            if logged_in:
                logger.info("✅ 检测到登录成功，自动关闭浏览器")
                return
            if (i + 1) % 6 == 0:
                logger.info(f"仍在等待登录…({(i+1)*5}s / 300s)")

        logger.warning("⏱️ 5 分钟内未检测到登录，请关闭浏览器后重试")


if __name__ == "__main__":
    asyncio.run(main())
