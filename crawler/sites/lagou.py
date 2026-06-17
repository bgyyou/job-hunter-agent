# -*- coding: utf-8 -*-
"""拉勾网 (lagou.com) crawler.

Robots.txt highlights:
  - Allow: /jobs/, /gongsi/, /html/
  - Disallow: /search/, /api/, /account/
  - Crawl-delay: not specified

Important notes:
  - 拉勾网使用 AJAX API 返回 JSON：
      POST https://www.lagou.com/jobs/v2/positionAjax.json
  - 接口需要 LGSUID 和 gatekeeper cookie，否则返回 403。
  - 本爬虫使用移动端 UA 模拟，降低被拦截概率。
  - 遇到 429 自动暂停 10 分钟。
  - 仅爬取公开岗位信息，不爬取任何个人隐私数据。

Cookie 设置：
  1. 在浏览器中访问 https://www.lagou.com
  2. 打开 DevTools → Application → Cookies
  3. 导出 LGSUID 和 gatekeeper 值到 data/cookies/lagou.json
"""

import re
import urllib.parse
from typing import Any, Dict, List, Optional

from loguru import logger

from crawler.base_crawler import BaseCrawler, CrawlerSettings


class LagouCrawler(BaseCrawler):
    """Crawl job listings from lagou.com via their mobile API."""

    BASE_URL = "https://www.lagou.com"
    API_URL = "https://www.lagou.com/jobs/v2/positionAjax.json"
    # Mobile UA to mimic iOS Safari
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

    def _base_url(self) -> str:
        return self.BASE_URL

    def _load_cookies(self) -> Dict[str, str]:
        """Merge cookie jar into a header dict."""
        cookie_str = "; ".join(
            f"{c['name']}={c['value']}" for c in self._cookies
        )
        return {"Cookie": cookie_str} if cookie_str else {}

    async def fetch_jobs(
        self,
        keyword: str = "Python",
        city: str = "全国",
        page: int = 1,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Fetch job listings from Lagou mobile API.

        Args:
            keyword: Search term.
            city: City code/name (default: 全国).
            page: Page number (1-indexed).
            limit: Max results to return.

        Returns:
            List of JD dicts with keys: title, company, salary, raw_text,
            skills, source_url, platform, etc.
        """
        if not self.can_fetch():
            logger.warning(f"[LagouCrawler] Daily limit reached ({self.settings.daily_limit})")
            return []

        results: List[Dict[str, Any]] = []
        page_size = min(limit, 20)  # API page size

        for p in range(page, page + 10):  # max 10 pages
            if len(results) >= limit:
                break

            body = {
                "first": str(p == page).lower(),
                "pn": p,
                "kd": urllib.parse.quote(keyword),
                "city": urllib.parse.quote(city),
                "needAddtionalResult": "false",
                "isSchoolJob": "0",
            }
            headers = {
                **self._headers(),
                "User-Agent": self.MOBILE_UA,
                **self._load_cookies(),
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Referer": f"https://www.lagou.com/jobs/list_{urllib.parse.quote(keyword)}?city={city}",
                "X-Anit-Forge-Code": "0",
                "X-Anit-Forge-Token": "auto",
            }

            client = await self._ensure_client()
            try:
                resp = await client.post(self.API_URL, data=body, headers=headers)

                if resp.status_code == 429:
                    logger.warning(
                        f"[LagouCrawler] 429 rate limited. Pausing 10 minutes."
                    )
                    self._domain_limiter.mark_blocked(self._domain)
                    return results

                if resp.status_code == 403:
                    logger.warning(
                        "[LagouCrawler] 403 — cookies may be invalid. "
                        "Try exporting fresh LGSUID/gatekeeper cookies."
                    )
                    self._domain_limiter.mark_blocked(self._domain)
                    return results

                resp.raise_for_status()
                data = resp.json()

                if data.get("code") != 200:
                    msg = data.get("msg", data.get("message", "unknown error"))
                    logger.warning(f"[LagouCrawler] API error code={data.get('code')}: {msg}")
                    break

                items = data.get("content", {}).get("positionResult", {}).get("result", [])
                if not items:
                    break

                for item in items:
                    if len(results) >= limit:
                        break
                    job = self._parse_job(item)
                    if job:
                        results.append(job)

            except Exception as exc:
                logger.error(f"[LagouCrawler] Request error: {exc}")
                break

        self.increment_count(len(results))
        logger.info(
            f"[LagouCrawler] Fetched {len(results)} jobs for '{keyword}' "
            f"(page {page}, daily remaining: {self.daily_remaining})"
        )
        return results

    def _parse_job(self, item: Dict) -> Optional[Dict[str, Any]]:
        """Extract structured fields from a Lagou API job item."""
        try:
            title = item.get("positionName", "").strip()
            company_name = item.get("companyShortName", "") or item.get("companyFullName", "")
            salary = item.get("salary", "")
            district = item.get("district", "")
            work_year = item.get("workYear", "")
            education = item.get("education", "")
            location = f"{district}".strip() if district else ""

            # Skills from label field
            skill_labels = item.get("label", "") or ""
            skills = [s.strip() for s in skill_labels.split(",") if s.strip()] if skill_labels else []

            # Position advantages as nice-to-have
            position_advantage = item.get("positionAdvantage", "") or ""

            # Fetch detail page for full description
            detail_url = item.get("href", "")
            raw_text = self._build_raw_text(item, detail_url)

            source_url = detail_url if detail_url.startswith("http") else f"{self.BASE_URL}{detail_url}"

            return {
                "title": title or "Untitled",
                "company": company_name or "Unknown",
                "location": location,
                "salary_str": salary,
                "experience_level": work_year,
                "education": education,
                "raw_text": raw_text[:10000],
                "skills_required": skills,
                "skills_nice": [position_advantage] if position_advantage else [],
                "source_url": source_url,
                "platform": "lagou",
                "search_keyword": "",
                "industry_tag": None,
                "function_tag": None,
                "position_tag": None,
                "auto_classified": 0,
            }
        except Exception as exc:
            logger.warning(f"[LagouCrawler] Parse error: {exc}")
            return None

    def _build_raw_text(self, item: Dict, detail_url: str) -> str:
        """Build raw_text from summary fields + optional detail page."""
        parts = []
        desc = item.get("jobDesc", "")
        req = item.get("liability", "")
        req2 = item.get("skills", "")
        for text in (desc, req, req2):
            if text:
                parts.append(text.strip())

        # If we have summary but no detail, try to fetch the detail page
        if not parts and detail_url:
            parts.append(f"Detail URL: {detail_url}")

        return "\n".join(parts)
