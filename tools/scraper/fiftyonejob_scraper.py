# -*- coding: utf-8 -*-
"""前程无忧 (51job) 爬虫。

v2.1 N10: 使用 Playwright 渲染 51job 搜索页，从 DOM 提取职位列表。

为什么用 Playwright：
- 51job 是纯 JS 渲染页面（SPA），API 需要动态 sign 参数（来自 interfaceacting.js），
  无法在服务器端伪造。
- 51job 搜索页无需登录，只需正确的浏览器环境 + 随机 UA。
- 对比猎聘：猎聘必须登录cookie才不触发风控；51job 登录反而增加被检测风险。

安全策略：
- 不使用任何已登录 profile，用干净浏览器环境
- 每个请求间隔 3-6s（正态分布）
- 触发验证码时自动暂停，不强行重试
- 使用 Edge 浏览器（Windows 兼容性最好）

用法：
    python scripts/collectors/batch_51job.py --keyword "AI产品经理" --per-keyword 20
    python scripts/collectors/batch_51job.py --default-keywords --per-keyword 20
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

from tools.scraper.base_scraper import BaseScraper
from tools.scraper.human_playwright_scraper import HumanPlaywrightScraper


class FiftyOneJobScraper(BaseScraper):
    """51job 爬虫（Playwright 渲染，无需登录）。

    51job 搜索页 URL 格式：
    https://we.51job.com/api/job/search?search_type=4&job_area=000000&page=1&page_size=20&keyword=...
    但 API 需要动态 sign 参数，故改用 Playwright 渲染搜索结果页后从 DOM 提取。
    """

    BASE_URL = "https://www.51job.com"
    API_BASE = "https://we.51job.com"

    # 搜索结果页（Playwright 渲染后从 DOM 提取）
    # 51job 的 /api/job/search 端点会触发验证码，必须用 /pc/search
    SEARCH_URL = "https://we.51job.com/pc/search"

    def __init__(
        self,
        headless: bool = True,
        human_speed: float = 0.5,
        user_data_dir: Optional[str] = None,
        request_interval_min: float = 3.0,
        request_interval_max: float = 6.0,
    ):
        super().__init__(
            platform_name="51job",
            base_url=self.API_BASE,
        )
        self.headless = headless
        self.human_speed = human_speed
        self.user_data_dir = user_data_dir
        self.request_interval_min = request_interval_min
        self.request_interval_max = request_interval_max
        self._playwright: Optional[HumanPlaywrightScraper] = None
        self._request_count = 0
        self._last_request_time = 0.0

    async def _init_playwright(self) -> None:
        if self._playwright is None:
            self._playwright = HumanPlaywrightScraper(
                platform_name="51job",
                headless=self.headless,
                human_speed=self.human_speed,
                browser_type="msedge",
                user_data_dir=self.user_data_dir,
            )
            await self._playwright.start()

    async def _close_playwright(self) -> None:
        if self._playwright:
            await self._playwright.close()
            self._playwright = None

    # ------------------------------------------------------------------
    # 防封：请求间隔（正态分布）
    # ------------------------------------------------------------------

    def _wait_interval(self) -> None:
        mean = (self.request_interval_min + self.request_interval_max) / 2
        std = (self.request_interval_max - self.request_interval_min) / 6
        delay = max(self.request_interval_min, min(self.request_interval_max, random.gauss(mean, std)))
        elapsed = time.time() - self._last_request_time
        sleep_time = max(0.1, delay - elapsed)
        time.sleep(sleep_time)
        self._last_request_time = time.time()

    # ------------------------------------------------------------------
    # 搜索（核心方法）
    # ------------------------------------------------------------------

    async def search_jobs(
        self,
        keyword: str,
        location: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """搜索 51job 职位（Playwright 渲染版）。

        Args:
            keyword: 关键词
            location: 城市中文名，None 表示全国（000000）
            page: 页码
            limit: 最大返回条数

        Returns:
            Job dicts: {platform, job_id, url, title, company, location,
                        salary_range, raw_text, scraped_at}
        """
        await self._init_playwright()
        self._wait_interval()

        try:
            # 51job /pc/search 的 URL 参数不会触发真实搜索，必须走 UI
            # 第 1 页：直接进搜索页 → 填关键词 → 点搜索按钮
            # 后续页：URL 拼接 ?page=N，搜索结果会保留
            if page == 1:
                await self._playwright.human_navigate(self.SEARCH_URL)
                await self._playwright.page.wait_for_load_state("networkidle", timeout=15000)
                await self._playwright.human_read_page(min_seconds=2.0, max_seconds=3.0)

                # 填搜索框
                ok = await self._fill_keyword(self._playwright.page, keyword)
                if not ok:
                    logger.warning(f"[51job] 找不到搜索框，跳过 keyword={keyword}")
                    return []

                # 点搜索按钮
                clicked = await self._click_search_button(self._playwright.page)
                if not clicked:
                    logger.warning(f"[51job] 找不到搜索按钮，尝试按 Enter")
                    await self._playwright.page.keyboard.press("Enter")
            else:
                # 第 2 页及之后：URL 带 page 参数
                search_url = (
                    f"{self.SEARCH_URL}?keyword={keyword}&jobArea=000000&page={page}"
                )
                await self._playwright.human_navigate(search_url)
                await self._playwright.page.wait_for_load_state("networkidle", timeout=15000)

            # 51job 搜索结果是懒加载
            await self._playwright.human_read_page(min_seconds=3.0, max_seconds=6.0)
            await self._scroll_to_load_jobs(self._playwright.page, target_count=limit)
            await self._playwright.take_screenshot(f"51job_search_{keyword[:4]}_{page}.png")

            page_obj = self._playwright.page
            body_text = await page_obj.evaluate("() => document.body.innerText") or ""

            # 51job 反爬关键词
            from tools.anti_bot import AntiBotDetector
            detector = AntiBotDetector()
            detected, reason = detector.detect_text(body_text)
            if detected:
                logger.warning(f"[51job] anti-bot detected: {reason}，暂停")
                await self._on_blocked()
                return []

            jobs = await self._extract_jobs_from_page(page_obj, keyword)
            logger.info(f"[51job] page={page} 提取到 {len(jobs)} 条")
            self._request_count += 1
            return jobs

        except Exception as e:
            logger.exception(f"[51job] search failed: {e}")
            return []

    async def _fill_keyword(self, page, keyword: str) -> bool:
        """在 51job 搜索框中填入关键词。"""
        try:
            box = await page.query_selector("input#keywordInput")
            if not box:
                box = await page.query_selector("input[placeholder*='公司'], input[placeholder*='职位']")
            if not box:
                return False
            await box.click()
            await page.wait_for_timeout(300)
            await box.fill("")
            await box.type(keyword, delay=80)
            await page.wait_for_timeout(500)
            return True
        except Exception as e:
            logger.debug(f"[51job] _fill_keyword failed: {e}")
            return False

    async def _click_search_button(self, page) -> bool:
        """点击 51job 搜索按钮。"""
        try:
            btn = await page.query_selector("div.search-btn")
            if not btn:
                btn = await page.query_selector(".search-box .btn, [class*='search-btn']")
            if not btn:
                return False
            await btn.click()
            return True
        except Exception as e:
            logger.debug(f"[51job] _click_search_button failed: {e}")
            return False

    async def _scroll_to_load_jobs(self, page, target_count: int = 10, max_rounds: int = 6) -> int:
        """滚动触发懒加载，直到 .joblist-item-job 数量稳定或达到 max_rounds。"""
        last_count = 0
        for i in range(max_rounds):
            try:
                count = await page.evaluate(
                    "() => document.querySelectorAll('div.joblist-item-job').length"
                )
            except Exception:
                count = 0
            if count >= target_count or count == last_count:
                if count > 0:
                    return count
            last_count = count
            await page.evaluate("() => window.scrollBy(0, 800)")
            await page.wait_for_timeout(1500)
        return last_count

    async def _extract_jobs_from_page(self, page, keyword: str) -> List[Dict[str, Any]]:
        """从渲染后的 DOM 提取职位列表（sensorsdata 解析版）。

        51job 搜索结果结构（2026）特性：
        - 容器: div.joblist-item-job
        - **不直接给职位详情链接**（公司链接用 .comp），反爬措施
        - 完整 jobId/jobTitle/salary/area 藏在容器 sensorsdata 属性（JSON）
        - 职位 title 在 .joblist-item-jobname（div，不是 a）
        - 公司名在 .comp（a，innerText 第一行）
        - 详情 URL 构造：https://jobs.51job.com/{jobid}.html
        """
        jobs: List[Dict[str, Any]] = []

        # 一次 evaluate 拉所有数据，避免多次 IPC
        items_data = await page.evaluate(
            """() => {
                const items = document.querySelectorAll('div.joblist-item-job');
                const result = [];
                for (const it of items) {
                    const sd = it.getAttribute('sensorsdata');
                    if (!sd) continue;
                    try {
                        const d = JSON.parse(sd);
                        const titleEl = it.querySelector('.joblist-item-jobname');
                        const compEl = it.querySelector('a.comp');
                        const tagsEl = it.querySelector('.joblist-item-tags');
                        const compText = compEl ? (compEl.innerText || '').split('\\n')[0].trim() : '';
                        result.push({
                            jobId: d.jobId || '',
                            jobTitle: (d.jobTitle || (titleEl ? titleEl.innerText : '') || '').trim(),
                            salary: d.jobSalary || '',
                            area: d.jobArea || '',
                            company: compText,
                            tags: tagsEl ? (tagsEl.innerText || '').replace(/\\s+/g, ' ').trim() : '',
                        });
                    } catch (e) { continue; }
                }
                return result;
            }"""
        )

        for d in items_data:
            job_id = d.get("jobId", "")
            title = d.get("jobTitle", "")
            if not job_id or not title:
                continue
            # 详情 URL 优先用短链，会 301 到完整带城市路径
            url = f"https://jobs.51job.com/{job_id}.html"
            raw_text = (
                f"标题:{title} 薪资:{d.get('salary','')} "
                f"公司:{d.get('company','')} 地点:{d.get('area','')} "
                f"标签:{d.get('tags','')}"
            ).strip(" |")
            jobs.append({
                "platform": "51job",
                "job_id": job_id,
                "url": url,
                "title": title[:120],
                "company": d.get("company", ""),
                "location": d.get("area", ""),
                "salary_range": d.get("salary", "")[:50],
                "raw_text": raw_text,
                "description": raw_text,
                "scraped_at": datetime.now().isoformat(),
                "search_keyword": keyword,
            })
            if len(jobs) >= 30:
                break

        return jobs

    @staticmethod
    async def _first_text_in(item, selectors: List[str]) -> str:
        """在指定元素内按顺序试 selector，返回第一个非空 inner_text。"""
        for sel in selectors:
            try:
                el = await item.query_selector(sel)
                if el:
                    txt = ((await el.inner_text()) or "").strip()
                    if txt:
                        return txt
            except Exception:
                continue
        return ""

    def _parse_job_data_text(self, text: str, keyword: str) -> List[Dict[str, Any]]:
        """解析从页面提取的文本数据。"""
        jobs: List[Dict[str, Any]] = []
        lines = text.split("\n")

        for line in lines:
            line = line.strip()
            if not line or len(line) < 5:
                continue
            # 过滤掉明显的非职位行
            if any(kw in line for kw in ["验证码", "登录", "注册", "人机验证", "请输入", "Copyright"]):
                continue
            # 职位链接
            m = re.search(r'(https?://[^\s|]+/job/\d+\.s?html)', line)
            if m:
                url = m.group(1)
                job_id = self._extract_job_id(url)
                title = line.split(url)[0].strip()[:120]
                if title and len(title) > 2:
                    jobs.append({
                        "platform": "51job",
                        "job_id": job_id,
                        "url": url,
                        "title": title,
                        "company": self._extract_field_from_text(line, "公司"),
                        "location": "",
                        "raw_text": line,
                        "description": line,
                        "scraped_at": datetime.now().isoformat(),
                        "search_keyword": keyword,
                    })
        return jobs

    @staticmethod
    def _extract_field_from_text(text: str, field: str) -> str:
        """简单从文本中提取字段（备用方案）。"""
        if not text:
            return ""
        m = re.search(rf'{field}[：:]\s*([^\n|]{{2,40}})', text)
        return m.group(1).strip() if m else ""

    @staticmethod
    def _extract_job_id(url: str) -> str:
        m = re.search(r"/job/(\d+)", url)
        return m.group(1) if m else url.split("/")[-1].replace(".html", "")

    async def parse_job(self, job_url: str) -> Dict[str, Any]:
        """获取职位详情（51job 详情页无需登录）。"""
        await self._init_playwright()
        self._wait_interval()
        try:
            await self._playwright.human_navigate(job_url)
            await self._playwright.human_read_page(min_seconds=2.0, max_seconds=4.0)

            page = self._playwright.page
            body_text = (await page.evaluate("() => document.body.innerText")) or ""

            from tools.anti_bot import AntiBotDetector
            detector = AntiBotDetector()
            detected, reason = detector.detect_text(body_text)
            if detected:
                logger.warning(f"[51job] parse_job anti-bot: {reason}")
                return {}

            title = await self._first_text(page, ["h1", ".job-title h1", "[class*='title']"])
            company = await self._first_text(page, [
                "[class*='company'] [class*='name']",
                ".company-name",
                "a[href*='/company/']",
            ])
            description = await self._first_text(page, [
                "[class*='job-intro']",
                "[class*='description']",
                ".content",
            ])

            return {
                "platform": "51job",
                "job_id": self._extract_job_id(job_url),
                "url": job_url,
                "title": title,
                "company": company,
                "description": description or body_text[:2000],
                "raw_text": description or body_text[:2000],
                "scraped_at": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.exception(f"[51job] parse_job failed: {e}")
            return {}

    async def get_job_detail(self, job_url: str) -> Dict[str, Any]:
        return await self.parse_job(job_url)

    async def check_login(self) -> bool:
        """51job 搜索页无需登录，始终返回 True。"""
        return True

    async def is_logged_in(self) -> bool:
        return await self.check_login()

    async def login(self, username: str = "", password: str = "") -> bool:
        return True

    async def _on_blocked(self) -> None:
        """被封后暂停 30 分钟。"""
        logger.warning("[51job] 触发反爬，暂停 30 分钟")
        await asyncio.sleep(1800)

    async def _first_text(self, page, selectors: List[str]) -> str:
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

    # ------------------------------------------------------------------
    # 城市代码
    # ------------------------------------------------------------------

    _CITY_CODES = {
        "全国": "000000", "北京": "010000", "上海": "020000", "深圳": "040000",
        "广州": "030200", "杭州": "080200", "南京": "070200", "苏州": "080900",
        "成都": "090200", "武汉": "180200", "西安": "230200", "重庆": "060000",
        "天津": "030000", "长沙": "180500", "郑州": "150200", "东莞": "040300",
        "佛山": "040200", "宁波": "080300", "无锡": "080200", "青岛": "120200",
        "大连": "230300", "沈阳": "230200", "济南": "120300", "福州": "110200",
        "厦门": "110300", "合肥": "150200", "昆明": "250200", "哈尔滨": "240200",
        "长春": "250300", "石家庄": "030200", "南昌": "170200", "贵阳": "260200",
        "太原": "230400", "兰州": "270200", "海口": "215200", "乌鲁木齐": "310200",
    }

    @classmethod
    def _city_to_code(cls, city: str) -> str:
        return cls._CITY_CODES.get(city, "000000")

    async def close(self) -> None:
        await self._close_playwright()
        logger.info(f"[51job] 生命周期结束，请求计数: {self._request_count}")

    async def __aenter__(self):
        await self._init_playwright()
        return self

    async def __aexit__(self, *args):
        await self.close()
