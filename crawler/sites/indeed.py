# -*- coding: utf-8 -*-
"""Indeed 中国 (cn.indeed.com) crawler.

Robots.txt highlights:
  - Allow: /jobs/, /sj/
  - Disallow: /ajax/, /api/, /m/, /cmp/, /searchajax/
  - Crawl-delay: not specified

Important notes:
  - Indeed 使用 HTML 页面返回搜索结果，需要 BeautifulSoup 解析。
  - 搜索 URL: https://cn.indeed.com/jobs?q=关键词&start=偏移量
  - 每页 10 条结果，start 参数递增（0, 10, 20...）
  - 每个岗位详情页需要额外请求获取完整描述。
  - 设置合理的请求间隔（3~5 秒），避免被临时封禁。
  - 仅爬取公开岗位信息，不爬取联系方式。
"""

import random
import time
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup
from loguru import logger

from crawler.base_crawler import BaseCrawler, CrawlerSettings


class IndeedCrawler(BaseCrawler):
    """Crawl job listings from cn.indeed.com via HTML parsing.

    Anti-403 strategy:
      1. Enhanced Chrome-like headers (Sec-Fetch, Cache-Control, etc.)
      2. Pre-fetch homepage to collect cookies before searching
      3. Retry with mobile UA + random delay on 403
      4. Stop after 3 consecutive 403s
    """

    BASE_URL = "https://cn.indeed.com"
    SEARCH_URL = "https://cn.indeed.com/jobs"
    HOME_URL = "https://cn.indeed.com/"

    # Desktop Chrome UA
    DESKTOP_UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )

    # Mobile UA fallback
    MOBILE_UA = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.0 Mobile/15E148 Safari/604.1"
    )

    def __init__(
        self,
        cookies: Optional[List[Dict[str, str]]] = None,
        settings: Optional[CrawlerSettings] = None,
    ):
        super().__init__(settings)
        self._cookies = cookies or []
        self._consecutive_403 = 0

    def _base_url(self) -> str:
        return self.BASE_URL

    def _load_cookies(self) -> Dict[str, str]:
        cookie_str = "; ".join(
            f"{c['name']}={c['value']}" for c in self._cookies
        )
        return {"Cookie": cookie_str} if cookie_str else {}

    def _enhanced_headers(self, ua: Optional[str] = None) -> Dict[str, str]:
        """Headers that closely mimic a real Chrome browser."""
        h = {
            "User-Agent": ua or self.DESKTOP_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": f"{self.BASE_URL}/",
            "Connection": "keep-alive",
            "Cache-Control": "max-age=0",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Upgrade-Insecure-Requests": "1",
        }
        h.update(self._load_cookies())
        return h

    async def fetch_jobs(
        self,
        keyword: str = "Python",
        city: str = "",
        page: int = 1,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Fetch job listings from Indeed China."""
        if not self.can_fetch():
            logger.warning(f"[IndeedCrawler] Daily limit reached ({self.settings.daily_limit})")
            return []

        # Pre-fetch homepage to collect cookies
        home_cookies = await self._fetch_homepage()

        results: List[Dict[str, Any]] = []
        page_size = 10
        start = (page - 1) * page_size
        self._consecutive_403 = 0  # reset on fresh crawl

        while len(results) < limit:
            try:
                jobs_on_this_page = await self._fetch_search_page(
                    keyword=keyword,
                    start=start,
                    location=city,
                    max_results=limit - len(results),
                    extra_cookies=home_cookies,
                )
                if not jobs_on_this_page:
                    break
                results.extend(jobs_on_this_page)
                start += page_size
            except Exception as exc:
                logger.error(f"[IndeedCrawler] Search page error: {exc}")
                break

        self.increment_count(len(results))
        logger.info(
            f"[IndeedCrawler] Fetched {len(results)} jobs for '{keyword}' "
            f"(daily remaining: {self.daily_remaining})"
        )
        return results

    async def _fetch_homepage(self) -> List[Dict[str, str]]:
        """GET homepage to collect initial cookies from Set-Cookie headers."""
        cookies: List[Dict[str, str]] = []
        client = await self._ensure_client()
        try:
            resp = await client.get(
                self.HOME_URL,
                headers={
                    **self._enhanced_headers(),
                    "Cookie": "",  # no cookies yet
                },
            )
            if resp.status_code == 200:
                # httpx stores cookies internally; extract them
                for c in resp.cookies.jar:
                    cookies.append({"name": c.name, "value": c.value})
                logger.info(f"[IndeedCrawler] Collected {len(cookies)} cookies from homepage")
            elif resp.status_code == 403:
                logger.warning("[IndeedCrawler] Homepage returned 403 — cookies unavailable")
        except Exception as exc:
            logger.warning(f"[IndeedCrawler] Homepage fetch failed: {exc}")
        return cookies

    async def _fetch_search_page(
        self,
        keyword: str,
        start: int,
        location: str,
        max_results: int,
        extra_cookies: Optional[List[Dict[str, str]]] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch a single search results page and parse job cards."""
        params = {"q": keyword, "start": start}
        if location:
            params["l"] = location

        headers = self._enhanced_headers(ua=self.DESKTOP_UA)

        # Merge homepage cookies into request cookie header
        if extra_cookies:
            cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in extra_cookies)
            existing = headers.get("Cookie", "")
            if existing:
                headers["Cookie"] = existing + "; " + cookie_str
            else:
                headers["Cookie"] = cookie_str

        client = await self._ensure_client()
        results: List[Dict[str, Any]] = []

        # ── Attempt 1: desktop UA ──
        html = await self._do_request(client, headers, params)
        if html is None:
            return results

        soup = BeautifulSoup(html, "html.parser")
        job_cards = soup.select("div.job_seen_bouncer, div[id^='popovers-'] a")
        if not job_cards:
            job_cards = soup.select("li.css-1ezmz7u")

        if not job_cards:
            logger.warning("[IndeedCrawler] No job cards found on page")
            return results

        logger.info(f"[IndeedCrawler] Found {len(job_cards)} job cards (start={start})")

        for card in job_cards[:max_results]:
            try:
                job = self._parse_search_card(card, soup)
                if job:
                    detail_url = job.get("source_url", "")
                    if detail_url:
                        detail_text = await self._fetch_detail(detail_url)
                        if detail_text:
                            job["raw_text"] = detail_text
                    results.append(job)
            except Exception as exc:
                logger.warning(f"[IndeedCrawler] Failed to parse card: {exc}")

        return results

    async def _do_request(
        self,
        client,
        headers: Dict[str, str],
        params: Dict[str, str],
        ua_overrides: Optional[Dict[str, str]] = None,
    ) -> Optional[str]:
        """Perform a GET request with 403 retry logic.

        Returns HTML text on success, None on failure.
        """
        max_attempts = 2  # desktop UA + mobile UA fallback

        for attempt in range(1, max_attempts + 1):
            try:
                resp = await client.get(
                    self.SEARCH_URL,
                    params=params,
                    headers=headers,
                    timeout=20,
                )

                if resp.status_code == 403:
                    self._consecutive_403 += 1
                    logger.warning(
                        f"[IndeedCrawler] 403 attempt {attempt}/{max_attempts} "
                        f"(consecutive={self._consecutive_403})"
                    )

                    if self._consecutive_403 >= 3:
                        logger.error(
                            "[IndeedCrawler] 3 consecutive 403s — Indeed may be blocking "
                            "this IP. Please visit https://cn.indeed.com manually to verify."
                        )
                        return None

                    if attempt == 1:
                        # Retry with mobile UA + random delay
                        delay = random.uniform(2.0, 4.0)
                        logger.info(f"[IndeedCrawler] Retrying with mobile UA after {delay:.1f}s delay")
                        time.sleep(delay)
                        headers = {
                            **headers,
                            "User-Agent": self.MOBILE_UA,
                        }
                        continue

                    # Second attempt also got 403 → stop
                    return None

                resp.raise_for_status()
                self._consecutive_403 = 0  # reset on success
                return resp.text

            except Exception as exc:
                logger.error(f"[IndeedCrawler] Request error: {exc}")
                return None

        return None

    async def _fetch_detail(self, url: str) -> Optional[str]:
        """Fetch a detail page and extract full job description."""
        if not url:
            return None

        headers = self._enhanced_headers(ua=self.DESKTOP_UA)
        client = await self._ensure_client()

        try:
            resp = await client.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            html = resp.text
        except Exception as exc:
            logger.warning(f"[IndeedCrawler] Detail fetch failed for {url}: {exc}")
            return None

        soup = BeautifulSoup(html, "html.parser")

        desc_selectors = [
            "div#jobdesc",
            "div[class*='jobsearch-JobDescriptions'] .jobsec",
            "div.jobsec",
            "div#description",
            "div[id*='description']",
            "div[class*='description']",
            "div#jobDescriptionText",
            "span[itemprop='description']",
            "div.css-1e7z4o5",
        ]

        for sel in desc_selectors:
            el = soup.select_one(sel)
            if el:
                text = el.get_text(separator="\n", strip=True)
                if text and len(text) > 50:
                    return text

        # Fallback: grab all paragraphs
        paragraphs = soup.select("p")
        if paragraphs:
            return "\n".join(
                p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)
            )[:10000]

        logger.debug(f"[IndeedCrawler] No description found on {url}")
        return None
