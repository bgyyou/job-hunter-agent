# -*- coding: utf-8 -*-
"""LiepinScraper - 猎聘爬虫。

v2.1 M6.B.3.2: 复用 human_playwright_scraper 的浏览器自动化基类，
与 JobsDBScraper 同款套路（搜索页 → 提链接 → parse 详情）。

猎聘反爬比 JobsDB 更狠，**必须先跑 `scripts/collectors/login_liepin.py`
完成首次登录**，之后复用 data/browser_profiles/liepin/ 的 cookie。
"""
from __future__ import annotations

import asyncio
import random
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from tools.anti_bot import AntiBotDetector

from .base_scraper import BaseScraper
from .human_playwright_scraper import HumanPlaywrightScraper


class LiepinScraper(BaseScraper):
    """猎聘爬虫（Playwright + Edge profile 复用）。"""

    def __init__(
        self,
        headless: bool = False,
        human_speed: float = 0.5,
        user_data_dir: Optional[str] = "data/browser_profiles/liepin",
        request_interval_min: float = 5.0,
        request_interval_max: float = 10.0,
    ):
        super().__init__(
            platform_name="liepin",
            base_url="https://www.liepin.com",
        )
        self.playwright_scraper: Optional[HumanPlaywrightScraper] = None
        self.headless = headless
        self.human_speed = human_speed
        self.user_data_dir = user_data_dir
        self.request_interval_min = request_interval_min
        self.request_interval_max = request_interval_max
        self._last_request_time = 0.0
        self.anti_bot = AntiBotDetector()

    # ------------------------------------------------------------------
    # 防封：请求间隔（正态分布）— 猎聘反爬比 51job 更严，间隔更大
    # ------------------------------------------------------------------

    def _wait_interval(self) -> None:
        mean = (self.request_interval_min + self.request_interval_max) / 2
        std = (self.request_interval_max - self.request_interval_min) / 6
        delay = max(self.request_interval_min, min(self.request_interval_max, random.gauss(mean, std)))
        elapsed = time.time() - self._last_request_time
        sleep_time = max(0.1, delay - elapsed)
        time.sleep(sleep_time)
        self._last_request_time = time.time()

    async def __aenter__(self):
        await self._init_playwright()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._close_playwright()

    async def _init_playwright(self):
        if not self.playwright_scraper:
            self.playwright_scraper = HumanPlaywrightScraper(
                platform_name="liepin",
                headless=self.headless,
                human_speed=self.human_speed,
                browser_type="msedge",
                user_data_dir=self.user_data_dir,
            )
            await self.playwright_scraper.start()

    async def _close_playwright(self):
        if self.playwright_scraper:
            await self.playwright_scraper.close()
            self.playwright_scraper = None

    # ------------------------------------------------------------------
    # 登录态健康检查（v2.1 M6.B.3.2 关键能力）
    # ------------------------------------------------------------------

    async def login(self, username: str = "", password: str = "") -> bool:
        """猎聘需要扫码登录，脚本无法自动完成，仅在已登录时返回 True。"""
        return await self.check_login()

    async def is_logged_in(self) -> bool:
        """BaseScraper 接口：检测当前 profile 是否仍处于登录态。"""
        return await self.check_login()

    async def check_login(self) -> bool:
        """检测当前 profile 是否仍处于登录态。

        改进版 v2.1 N10：使用 DOM 元素检测而非纯文本匹配，更稳定。
        - 登录态：右上角有「个人中心 / 我的简历 / 退出」入口
        - 未登录：显示「登录 / 注册」按钮
        """
        await self._init_playwright()
        try:
            await self.playwright_scraper.human_navigate(f"{self.base_url}/")
            await self.playwright_scraper.human_read_page(min_seconds=1.5, max_seconds=3.0)
            page = self.playwright_scraper.page

            # 方法1：DOM 元素检测（主方案，比文字更稳定）
            logged_in = await self._is_logged_in_via_dom(page)

            # 方法2：文字备用检测（双重保险）
            if not logged_in:
                body_text = await page.evaluate("() => document.body.innerText")
                logged_in = (
                    "个人中心" in body_text
                    or "我的简历" in body_text
                    or "退出" in body_text
                )

            if not logged_in:
                # 再检查：是否有「登录/注册」按钮（确认是未登录）
                login_text_found = await self._page_has_text(page, "登录/注册") or \
                                   await self._page_has_text(page, "登录")
                if login_text_found:
                    logger.warning(
                        "[liepin] 登录态失效：检测到「登录/注册」按钮。"
                        "请跑 `python scripts/collectors/login_liepin.py` 重新登录。"
                    )
                else:
                    logger.warning(
                        "[liepin] 登录态不明：未检测到个人中心也未检测到登录按钮，"
                        "可能是页面加载不完整。"
                    )

            return logged_in
        except Exception as e:
            logger.exception(f"[liepin] check_login 失败: {e}")
            return False

    async def _is_logged_in_via_dom(self, page) -> bool:
        """DOM 元素检测是否已登录。"""
        # 登录后会出现：个人中心链接、退出按钮、用户头像区域
        logged_in_selectors = [
            # 链接型
            "a[href*='usercenter']",
            "a[href*='personal-center']",
            "a[href*='myresume']",
            "a[href*='resume']",
            # 按钮型
            "button:has-text('退出')",
            "[class*='logout']",
            "[class*='exit']",
            # 头像/用户名区域
            "[class*='avatar']",
            "[class*='user-name']",
            "[class*='username']",
            "[class*='user-info']",
            # 新版2026
            "[class*='header-user']",
            "[class*='user-panel']",
            "[class*='lp-header']",
        ]

        for sel in logged_in_selectors:
            try:
                el = await page.query_selector(sel)
                if el:
                    # 元素存在，检查是否可见（display:none 等）
                    is_visible = await el.is_visible()
                    if is_visible:
                        return True
            except Exception:
                continue

        return False

    async def _page_has_text(self, page, text: str) -> bool:
        """检查页面是否包含指定文字。"""
        try:
            body_text = await page.evaluate("() => document.body.innerText")
            return text in body_text
        except Exception:
            return False

    # ------------------------------------------------------------------
    # 搜索
    # ------------------------------------------------------------------

    async def search_jobs(
        self,
        keyword: str,
        city: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """搜索职位。

        Args:
            keyword: 关键词，如 "AI产品经理"
            city: 城市中文名，如 "深圳"；None 表示全国
            page: 页码（从 1 起）
            limit: 最多返回多少条
        """
        await self._init_playwright()
        self._wait_interval()

        # 猎聘搜索 URL 形如 https://www.liepin.com/zhaopin/?key=AI产品经理&city=深圳&curPage=0
        params = [f"key={keyword}"]
        if city:
            params.append(f"city={city}")
        if page > 1:
            params.append(f"curPage={page - 1}")
        search_url = f"{self.base_url}/zhaopin/?" + "&".join(params)

        logger.info(f"[liepin] search: {search_url}")
        try:
            await self.playwright_scraper.human_navigate(search_url)
            await self.playwright_scraper.human_read_page(min_seconds=2.0, max_seconds=4.0)
            await self.playwright_scraper.take_screenshot("liepin_search.png")

            jobs = await self._extract_jobs_from_page()
            logger.info(f"[liepin] 提取到 {len(jobs)} 条职位")
            return jobs[:limit]
        except Exception as e:
            logger.exception(f"[liepin] search 失败: {e}")
            return []

    async def _extract_jobs_from_page(self) -> List[Dict[str, Any]]:
        jobs: List[Dict[str, Any]] = []
        try:
            page = self.playwright_scraper.page

            # 猎聘职位卡片：a.job-title / .job-info a；详情链接形如 /job/XXXXXX.shtml
            links = await page.query_selector_all("a[href*='/job/']")

            seen = set()
            for link in links:
                href = (await link.get_attribute("href")) or ""
                if not href or "/job/" not in href:
                    continue
                full = href if href.startswith("http") else self.base_url + href
                if full in seen:
                    continue
                seen.add(full)

                title = ((await link.inner_text()) or "").strip()[:120]
                job_id = self._extract_job_id(full)
                jobs.append({
                    "platform": "liepin",
                    "job_id": job_id,
                    "url": full,
                    "title": title,
                    "company": "",
                    "location": "",
                    "description": "",
                    "scraped_at": datetime.now().isoformat(),
                })
                if len(jobs) >= 30:
                    break
        except Exception as e:
            logger.exception(f"[liepin] _extract_jobs_from_page 失败: {e}")
        return jobs

    @staticmethod
    def _extract_job_id(url: str) -> str:
        m = re.search(r"/job/(\d+)", url)
        return m.group(1) if m else url.split("/")[-1].split("?")[0]

    # ------------------------------------------------------------------
    # 详情
    # ------------------------------------------------------------------

    async def parse_job(self, job_url: str) -> Dict[str, Any]:
        await self._init_playwright()
        self._wait_interval()
        try:
            await self.playwright_scraper.human_navigate(job_url)
            await self.playwright_scraper.human_read_page(min_seconds=2.0, max_seconds=4.0)
            await self.playwright_scraper.take_screenshot("liepin_detail.png")

            page = self.playwright_scraper.page

            # 猎聘 2026 详情页 DOM 经常调整 class 名，靠固定 selector 太脆。
            title = await self._first_text(page, ["h1", ".job-title-left .name", ".name", "[class*='job-title']"])
            company = await self._first_text(page, [
                "[class*='company-info'] [class*='name']",
                "[class*='ent-name']",
                ".company-name",
                "a[href*='/company/']",
            ])
            location = await self._first_text(page, [
                "[class*='job-properties']",
                "[class*='job-info']",
                "[class*='basic-info']",
                ".job-area",
            ])

            body_text = ((await page.evaluate("() => document.body.innerText")) or "").strip()
            detected, reason = self.anti_bot.detect_text(body_text)
            if detected:
                logger.warning(f"[liepin] parse_job skipped anti-bot page: {reason} {job_url}")
                return {}

            description = await self._first_text(page, [
                "[class*='job-intro']",
                "[class*='job-description']",
                ".content.content-word",
                ".job-item .content",
                "[class*='describe']",
            ])
            description = (description or "").strip()
            if not description:
                logger.warning(f"[liepin] parse_job skipped: no job description selector matched {job_url}")
                return {}
            if len(description) < 80:
                logger.warning(f"[liepin] parse_job skipped: description too short {job_url}")
                return {}

            detected, reason = self.anti_bot.detect_text(description)
            if detected:
                logger.warning(f"[liepin] parse_job skipped anti-bot description: {reason} {job_url}")
                return {}

            return {
                "platform": "liepin",
                "job_id": self._extract_job_id(job_url),
                "url": job_url,
                "title": title,
                "company": company,
                "location": location,
                "description": description,
                "raw_text": description,
                "scraped_at": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.exception(f"[liepin] parse_job 失败: {e}")
            raise RuntimeError(f"猎聘详情解析失败: {e}") from e

    @staticmethod
    async def _first_text(page, selectors: List[str]) -> str:
        """按顺序试 selector，返回第一个命中的 inner_text；都没命中返回空串。"""
        for sel in selectors:
            try:
                el = await page.query_selector(sel)
                if el:
                    txt = (await el.inner_text()).strip()
                    if txt:
                        return txt
            except Exception:
                continue
        return ""

    async def get_job_detail(self, job_url: str) -> Dict[str, Any]:
        """parse_job 别名，与 JobsDBScraper 接口对齐供 batch_*.py 共用。"""
        return await self.parse_job(job_url)

    async def close(self):
        """关闭 Playwright，与 JobsDBScraper 接口对齐。"""
        await self._close_playwright()
