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
    print("3. 登录成功后回到终端按 Enter 关闭浏览器")
    print("4. 之后 LiepinScraper 会自动复用该 profile")
    print()

    async with LiepinScraper(headless=False) as scraper:
        await scraper.playwright_scraper.human_navigate("https://www.liepin.com/")
        logger.info("等待用户登录…")
        input("✅ 已登录后按 Enter 关闭浏览器…")

        ok = await scraper.check_login()
        if ok:
            logger.info("✅ 登录态校验通过")
        else:
            logger.warning("⚠️ 未检测到登录态，请重新登录")


if __name__ == "__main__":
    asyncio.run(main())
