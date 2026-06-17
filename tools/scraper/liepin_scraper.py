# -*- coding: utf-8 -*-
"""LiepinScraper - 猎聘爬虫。

v2.1 M6.B.3.2: 复用 human_playwright_scraper 的浏览器自动化基类，
与 JobsDBScraper 同款套路（搜索页 → 提链接 → parse 详情）。

猎聘反爬比 JobsDB 更狠，**必须先跑 `scripts/collectors/login_liepin.py`
完成首次登录**，之后复用 data/browser_profiles/liepin/ 的 cookie。
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from .base_scraper import BaseScraper
from .human_playwright_scraper import HumanPlaywrightScraper


class LiepinScraper(BaseScraper):
    """猎聘爬虫（Playwright + Edge profile 复用）。"""

    def __init__(
        self,
        headless: bool = False,
        human_speed: float = 0.5,
        user_data_dir: Optional[str] = "data/browser_profiles/liepin",
    ):
        super().__init__(
            platform_name="liepin",
            base_url="https://www.liepin.com",
        )
        self.playwright_scraper: Optional[HumanPlaywrightScraper] = None
        self.headless = headless
        self.human_speed = human_speed
        self.user_data_dir = user_data_dir

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

    async def check_login(self) -> bool:
        """检测当前 profile 是否仍处于登录态。

        猎聘未登录时搜索页/详情页会重定向到登录页或弹强制登录 modal。
        我们用首页的「用户头像 / 退出按钮」做判定。
        """
        await self._init_playwright()
        try:
            await self.playwright_scraper.human_navigate(f"{self.base_url}/")
            await self.playwright_scraper.human_read_page(min_seconds=1.0, max_seconds=2.0)
            # 登录后右上角会有 .user-info 或类似节点
            sel = await self.playwright_scraper.page.query_selector_all(
                ".user-info, .header-user, a[href*='logout'], .user-name"
            )
            ok = bool(sel)
            if not ok:
                logger.warning(
                    "[liepin] 登录态失效：未在首页找到用户节点。"
                    "请跑 `python scripts/collectors/login_liepin.py` 重新登录。"
                )
            return ok
        except Exception as e:
            logger.exception(f"[liepin] check_login 失败: {e}")
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
        try:
            await self.playwright_scraper.human_navigate(job_url)
            await self.playwright_scraper.human_read_page(min_seconds=2.0, max_seconds=4.0)
            await self.playwright_scraper.take_screenshot("liepin_detail.png")

            page = self.playwright_scraper.page
            title_el = await page.query_selector(".job-title, .name, h1")
            title = (await title_el.inner_text()).strip() if title_el else ""

            company_el = await page.query_selector(".company-name, .ellipsis-1, .ent-name")
            company = (await company_el.inner_text()).strip() if company_el else ""

            location_el = await page.query_selector(".job-info-text, .job-area, .basic-info-item")
            location = (await location_el.inner_text()).strip() if location_el else ""

            # 详情正文：猎聘用 .job-description / .content.content-word
            desc_el = await page.query_selector(
                ".job-description, .content.content-word, .job-item .content"
            )
            description = (await desc_el.inner_text()).strip() if desc_el else ""

            return {
                "platform": "liepin",
                "job_id": self._extract_job_id(job_url),
                "url": job_url,
                "title": title,
                "company": company,
                "location": location,
                "description": description,
                "raw_text": description or "",
                "scraped_at": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.exception(f"[liepin] parse_job 失败: {e}")
            raise RuntimeError(f"猎聘详情解析失败: {e}") from e
