# -*- coding: utf-8 -*-
"""Boss直聘 (zhipin.com) crawler.

Robots.txt highlights:
  - Allow: /html/job.html, /html/sitemap.html
  - Disallow: /user/, /muser/
  - Crawl-delay: not specified

Important notes:
  - Boss直聘 uses AJAX API for job listings:
      GET https://www.zhipin.com/wapi/zp/geek/job/json.json?city=&page=&size=
  - The API requires cookies (device_id, __zp_stoken__) set after login.
  - Without valid cookies, the API returns 403/redirect to login.
  - This crawler targets the JSON API for efficiency (no browser needed).
  - Rate limit: max 20 requests/min per domain. Respect CRAWLER_RATE_LIMIT.
  - DO NOT scrape user personal data (email, phone, etc.).

Cookie setup:
  1. Log in at https://www.zhipin.com in a real browser.
  2. Export cookies (device_id, __zp_stoken__) to data/cookies/boss.json.
  3. The pipeline will load them automatically.

Playwright Edge 复用模式:
  --use-browser 参数会在 cookies 不可用时自动回退到 Playwright。
  启动时复用本机 Edge 的登录态，需提前在 Edge 中登录 boss 直聘
  并关闭所有 Edge 窗口（Playwright 需要独占用户目录）。
"""

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from crawler.base_crawler import BaseCrawler, CrawlerSettings


class BossCrawler(BaseCrawler):
    """Crawl job listings from zhipin.com via their JSON API.

    Fallback: when no cookies are available, uses Playwright with
    local Edge user-data to reuse an existing login session.
    """

    BASE_URL = "https://www.zhipin.com"
    API_URL = "https://www.zhipin.com/wapi/zp/geek/job/json.json"
    SEARCH_URL = "https://www.zhipin.com/job_detail/?query={query}&city={city}"

    def __init__(
        self,
        cookies: Optional[List[Dict[str, str]]] = None,
        settings: Optional[CrawlerSettings] = None,
        use_browser: bool = False,
        edge_user_data_dir: Optional[str] = None,
        edge_profile: str = "Default",
    ):
        super().__init__(settings)
        self._cookies = cookies or []
        self._use_browser = use_browser
        self._edge_user_data_dir = edge_user_data_dir
        self._edge_profile = edge_profile

        # Lazy Playwright browser instance
        self._browser = None
        self._context = None
        self._page = None

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
        city: str = "101010100",
        page: int = 1,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Fetch job listings from Boss直聘.

        Priority:
          1. If cookies provided → JSON API (fast, no browser)
          2. If use_browser=True and no cookies → Playwright Edge reuse
          3. Otherwise → JSON API (will get 403 if no cookies)
        """
        if not self.can_fetch():
            logger.warning(f"[BossCrawler] Daily limit reached ({self.settings.daily_limit})")
            return []

        # ── Path 1: cookies-based JSON API ──
        if self._cookies:
            return await self._fetch_via_api(keyword, city, page, limit)

        # ── Path 2: Playwright browser fallback ──
        if self._use_browser:
            return await self._fetch_via_browser(keyword, city, limit)

        # ── Path 3: no cookies, no browser → still try API ──
        logger.warning(
            "[BossCrawler] No cookies provided. "
            "Use --cookies or --use-browser for authenticated scraping."
        )
        return await self._fetch_via_api(keyword, city, page, limit)

    async def _fetch_via_api(
        self,
        keyword: str,
        city: str,
        page: int,
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Fetch via JSON API (requires cookies for auth)."""
        params = {
            "query": keyword,
            "city": city,
            "page": page,
            "size": min(limit, 20),
        }
        headers = {**self._headers(), **self._load_cookies()}

        client = await self._ensure_client()
        results: List[Dict[str, Any]] = []

        try:
            resp = await client.get(self.API_URL, params=params, headers=headers)

            if resp.status_code == 403:
                logger.warning(
                    "[BossCrawler] 403 — cookies may be expired or invalid. "
                    "Try --cookies or --use-browser"
                )
                self._domain_limiter.mark_blocked(self._domain)
                return []

            resp.raise_for_status()
            data = resp.json()

            items = data.get("list", {}).get("job_list", []) or data.get("list", []) or []

            for item in items:
                job = self._parse_job(item)
                if job:
                    results.append(job)
                if len(results) >= limit:
                    break

        except Exception as exc:
            logger.error(f"[BossCrawler] API fetch error: {exc}")

        self.increment_count(len(results))
        logger.info(
            f"[BossCrawler] API fetched {len(results)} jobs for '{keyword}' "
            f"(page {page}, daily remaining: {self.daily_remaining})"
        )
        return results

    async def _fetch_via_browser(
        self,
        keyword: str,
        city: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Fallback: use Playwright to reuse Edge login session."""
        results: List[Dict[str, Any]] = []

        # Ensure browser is started
        page = await self._get_browser_page()
        if page is None:
            logger.error("[BossCrawler] Browser init failed, cannot fetch")
            return []

        try:
            search_url = self.SEARCH_URL.format(
                query=keyword, city=city
            )
            logger.info(f"[BossCrawler] Opening search page: {search_url}")
            await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)

            # Wait for job list to render
            try:
                await page.wait_for_selector(
                    ".job-card-wrapper", timeout=15000
                )
            except Exception:
                logger.warning(
                    "[BossCrawler] Job cards not found on page (possible login required). "
                    "Refreshing page..."
                )
                await page.reload(wait_until="domcontentloaded")
                try:
                    await page.wait_for_selector(".job-card-wrapper", timeout=10000)
                except Exception:
                    logger.warning(
                        "[BossCrawler] Still no job cards after reload. "
                        "Page may be prompting for login."
                    )
                    # Take screenshot for debugging
                    import os
                    screenshot_path = str(
                        Path(self.settings.cache_dir) / "boss_crawler_screenshot.png"
                    )
                    await page.screenshot(path=screenshot_path, full_page=False)
                    logger.info(f"[BossCrawler] Screenshot saved: {screenshot_path}")
                    return []

            # Extract job cards
            cards = await page.query_selector_all(".job-card-wrapper")
            logger.info(f"[BossCrawler] Found {len(cards)} job cards on page")

            for card in cards[:limit]:
                try:
                    job = await self._parse_job_from_card(card)
                    if job:
                        results.append(job)
                except Exception as exc:
                    logger.warning(f"[BossCrawler] Failed to parse job card: {exc}")

        except Exception as exc:
            logger.error(f"[BossCrawler] Browser fetch error: {exc}")

        self.increment_count(len(results))
        logger.info(
            f"[BossCrawler] Browser fetched {len(results)} jobs for '{keyword}' "
            f"(daily remaining: {self.daily_remaining})"
        )
        return results

    async def _get_browser_page(self):
        """Get or create a Playwright page reusing Edge user data (async API).

        Diagnostics:
          - Logs detected LOCALAPPDATA, resolved user_data_dir, profile name
          - Checks if user_data_dir exists; if not, prints actionable hint
          - Scans for leftover msedge.exe processes that may hold the lock
          - Reports lock-related errors with explicit "close all Edge" message

        Uses launch_persistent_context() to properly load the Edge user-data
        directory (the --user-data-dir CLI flag is not supported by Playwright
        for Chromium; use launch_persistent_context instead).
        """
        if self._page is not None and not self._page.is_closed():
            return self._page

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error(
                "[BossCrawler] playwright not installed. "
                "Run: pip install playwright && playwright install msedge"
            )
            return None

        # ── Resolve & log Edge user-data dir ──
        user_data_dir = self._resolve_edge_user_data()
        profile_dir = self._edge_profile

        if user_data_dir:
            logger.info(
                f"[BossCrawler] Edge config: "
                f"LOCALAPPDATA={os.environ.get('LOCALAPPDATA', '<unset>')} | "
                f"user_data_dir={user_data_dir} | profile={profile_dir}"
            )
            if not os.path.isdir(user_data_dir):
                logger.error(
                    f"[BossCrawler] Edge user-data dir DOES NOT EXIST: {user_data_dir}\n"
                    f"  This usually means:\n"
                    f"  1. Microsoft Edge is not installed, or\n"
                    f"  2. Edge has never been launched (no profile created yet)\n"
                    f"  3. Edge was installed to a non-standard location.\n"
                    f"  Try launching Edge once manually, then close all Edge windows."
                )
                user_data_dir = None
            else:
                # Check for lock file
                lock_path = os.path.join(user_data_dir, "SingletonLock")
                if os.path.exists(lock_path):
                    logger.warning(
                        f"[BossCrawler] Lock file exists: {lock_path}\n"
                        f"  This means Edge may still be running. Please close ALL Edge windows."
                    )
        else:
            logger.warning("[BossCrawler] Could not resolve Edge user-data dir (LOCALAPPDATA unset?)")

        # ── Check for leftover msedge.exe processes ──
        leftover_procs = self._check_leftover_processes()
        if leftover_procs:
            logger.warning(
                f"[BossCrawler] Found {len(leftover_procs)} leftover msedge.exe process(es):\n"
                f"  {'; '.join(leftover_procs)}\n"
                f"  Please close ALL Edge windows before running again."
            )

        # ── Launch browser with 2-tier fallback ──
        browser = None
        context = None
        launch_errors: List[str] = []

        async with async_playwright() as p:
            # Attempt 1: launch_persistent_context with Edge channel
            if user_data_dir:
                try:
                    # launch_persistent_context is the ONLY way to pass user_data_dir
                    # in Playwright. We pass profile dir via args for the launched browser.
                    context = await p.chromium.launch_persistent_context(
                        user_data_dir=user_data_dir,
                        channel="msedge",
                        headless=False,
                        args=[
                            "--disable-blink-features=AutomationControlled",
                            "--disable-features=msEdgeAutofillAtFormSubmission",
                            "--disable-infobars",
                            "--disable-extensions",
                            "--no-first-run",
                            "--no-default-browser-check",
                        ],
                    )
                    browser = context.browser
                    logger.info(
                        f"[BossCrawler] Launched Edge via launch_persistent_context "
                        f"(channel='msedge', user_data_dir={user_data_dir})"
                    )
                except Exception as e:
                    err_msg = str(e)
                    launch_errors.append(f"persistent_context+msedge: {err_msg}")
                    logger.debug(f"[BossCrawler] persistent_context+msedge failed: {e}")
                    if "lock" in err_msg.lower() or "in use" in err_msg.lower():
                        logger.error(
                            f"[BossCrawler] Browser data directory is locked!\n"
                            f"  {err_msg}\n"
                            f"  Please close ALL Edge windows (including background tasks) "
                            f"and try again."
                        )
                    else:
                        logger.warning(f"[BossCrawler] persistent_context+msedge launch failed: {e}")

            # Attempt 2: launch_persistent_context with default Chromium
            if context is None and user_data_dir:
                try:
                    context = await p.chromium.launch_persistent_context(
                        user_data_dir=user_data_dir,
                        headless=False,
                        args=[
                            "--disable-blink-features=AutomationControlled",
                            "--disable-features=msEdgeAutofillAtFormSubmission",
                            "--disable-infobars",
                            "--disable-extensions",
                            "--no-first-run",
                            "--no-default-browser-check",
                        ],
                    )
                    browser = context.browser
                    logger.info(
                        f"[BossCrawler] Launched Chromium via launch_persistent_context "
                        f"(user_data_dir={user_data_dir}, profile={profile_dir})"
                    )
                except Exception as e:
                    err_msg = str(e)
                    launch_errors.append(f"persistent_context+chromium: {err_msg}")
                    logger.debug(f"[BossCrawler] persistent_context+chromium failed: {e}")
                    if "lock" in err_msg.lower() or "in use" in err_msg.lower():
                        logger.error(
                            f"[BossCrawler] Browser data directory is locked!\n"
                            f"  {err_msg}\n"
                            f"  Please close ALL Edge windows (including background tasks) "
                            f"and try again."
                        )
                    else:
                        logger.warning(f"[BossCrawler] persistent_context+chromium launch failed: {e}")

            # Attempt 3: ephemeral browser (no user-data dir — last resort)
            if context is None:
                try:
                    browser = await p.chromium.launch(
                        headless=False,
                        args=[
                            "--disable-blink-features=AutomationControlled",
                            "--disable-extensions",
                            "--no-first-run",
                        ],
                    )
                    context = await browser.new_context(
                        viewport={"width": 1920, "height": 1080},
                        locale="zh-CN",
                        user_agent=(
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0"
                        ),
                    )
                    logger.warning(
                        "[BossCrawler] Launched WITHOUT user-data dir — "
                        "no login session will be available. "
                        "Boss直聘 will likely return 403."
                    )
                except Exception as e:
                    logger.error(f"[BossCrawler] Browser launch failed: {e}")
                    if launch_errors:
                        logger.error(f"  Previous errors: {'; '.join(launch_errors)}")
                    return None

            # ── Create page from context ──
            pages = context.pages
            page = pages[-1] if pages else await context.new_page()

            # Hide webdriver automation flag
            await page.add_init_script(
                """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                """
            )

            # Remove Edge "controlled by automation" banner
            await page.add_init_script(
                """
                const observer = new MutationObserver(() => {
                    const banner = document.querySelector(
                        '[class*="automation"], [class*="controlled"], [class*="automation-control"]'
                    );
                    if (banner) banner.remove();
                });
                observer.observe(document.body, { childList: true, subtree: true });
                try {
                    document.querySelectorAll('[class*="DevToolsIndicator"]').forEach(el => el.remove());
                } catch(e) {}
                """
            )

            self._browser = browser
            self._context = context
            self._page = page

        return self._page

    def _check_leftover_processes(self) -> List[str]:
        """Scan for leftover msedge.exe processes that may lock the user-data dir."""
        procs: List[str] = []
        try:
            import subprocess
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq msedge.exe", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().splitlines():
                    # CSV format: ["msedge.exe","PID",...]
                    parts = line.replace('"', '').split(',')
                    if parts and parts[0] == 'msedge.exe':
                        pid = parts[1] if len(parts) > 1 else '?'
                        procs.append(f"msedge.exe (PID {pid})")
        except Exception as e:
            logger.debug(f"[BossCrawler] Process scan failed: {e}")
        return procs

    async def _parse_job_from_card(self, card) -> Optional[Dict[str, Any]]:
        """Extract job info from a Playwright job card element."""
        try:
            title_el = await card.query_selector(".job-name")
            company_el = await card.query_selector(".company-name")
            salary_el = await card.query_selector(".salary")
            info_el = await card.query_selector(".job-info")

            title = (await title_el.inner_text()) if title_el else ""
            company = (await company_el.inner_text()) if company_el else ""
            salary = (await salary_el.inner_text()) if salary_el else ""
            info_text = (await info_el.inner_text()) if info_el else ""

            # Combine info text for experience/education
            experience = ""
            education = ""
            parts = [p.strip() for p in info_text.split("/") if p.strip()]
            for part in parts:
                if "年" in part and ("应届" in part or "毕业" in part):
                    education = part
                elif "年" in part:
                    experience = part

            source_url = ""
            try:
                link = await card.query_selector("a")
                if link:
                    href = await link.get_attribute("href")
                    if href:
                        source_url = href if href.startswith("http") else self.BASE_URL + href
            except Exception:
                source_url = f"{self.BASE_URL}/job/"

            raw_text = f"{title}\n{company}\n{info_text}".strip()

            return {
                "title": title.strip(),
                "company": company.strip(),
                "location": "",
                "salary_str": salary.strip(),
                "experience_level": experience,
                "education": education,
                "raw_text": raw_text[:10000],
                "skills_required": [],
                "skills_nice": [],
                "source_url": source_url,
                "platform": "boss",
                "search_keyword": "",
                "industry_tag": None,
                "function_tag": None,
                "position_tag": None,
                "auto_classified": 0,
            }
        except Exception as exc:
            logger.warning(f"[BossCrawler] Card parse error: {exc}")
            return None

    def _resolve_edge_user_data(self) -> Optional[str]:
        """Get Edge user-data directory path."""
        if self._edge_user_data_dir:
            return self._edge_user_data_dir
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            return os.path.join(local_appdata, "Microsoft", "Edge", "User Data")
        return None

    def _parse_job(self, item: Dict) -> Optional[Dict[str, Any]]:
        """Extract structured fields from a Boss API job item."""
        try:
            base = item.get("job_detail", item)
            if not isinstance(base, dict):
                return None

            title = base.get("job_name", "").strip()
            company_name = base.get("company", {}).get("name", "") or base.get("company_name", "")
            area = base.get("area", "")
            district = base.get("district", "")
            location = f"{area}{district}".strip() or base.get("city_name", "")

            salary_min = base.get("salary_low", "")
            salary_max = base.get("salary_high", "")
            salary_str = f"{salary_min}-{salary_max}" if salary_min and salary_max else str(base.get("salary", ""))

            experience = base.get("job_experience", {}).get("name", "") or base.get("experience", "")
            education = base.get("job_edu", {}).get("name", "") or base.get("education", "")

            description = base.get("description", "") or base.get("job_desc", "")
            requirements = base.get("requirements", "") or base.get("job_require", "")

            # Build raw_text from description + requirements
            raw_parts = [d.strip() for d in (description, requirements) if d]
            raw_text = "\n".join(raw_parts)

            # Extract skills from requirements text
            skills_required = self._extract_skills(requirements)
            skills_nice = self._extract_wanted_skills(description)

            source_url = base.get("href", "") or f"{self.BASE_URL}/job/detail/{item.get('id', '')}.html"

            return {
                "title": title or "Untitled",
                "company": company_name or "Unknown",
                "location": location,
                "salary_str": salary_str,
                "experience_level": experience,
                "education": education,
                "raw_text": raw_text,
                "skills_required": skills_required,
                "skills_nice": skills_nice,
                "source_url": source_url,
                "platform": "boss",
                "search_keyword": item.get("query", ""),
                "industry_tag": None,
                "function_tag": None,
                "position_tag": None,
                "auto_classified": 0,
            }
        except Exception as exc:
            logger.warning(f"[BossCrawler] Parse error: {exc}")
            return None

    @staticmethod
    def _extract_skills(text: str) -> List[str]:
        """Heuristic skill extraction from requirement text."""
        if not text:
            return []
        skills: List[str] = []
        patterns = [
            r"(\d+)\s*年以上",
            r"精通[\s：:]*(.+?)[，,。.]?",
            r"熟练[\s：:]*(.+?)[，,。.]?",
            r"熟悉[\s：:]*(.+?)[，,。.]?",
            r"掌握[\s：:]*(.+?)[，,。.]?",
            r"(\w{2,8}编程)",
            r"(\w{2,8}框架)",
            r"(\w{2,8}语言)",
            r"(\w{2,8}数据库)",
            r"(\w{2,8}中间件)",
        ]
        for pat in patterns:
            matches = re.findall(pat, text)
            skills.extend(m for m in matches if m not in skills)
        return skills[:20]

    @staticmethod
    def _extract_wanted_skills(text: str) -> List[str]:
        """Extract preferred qualifications (nice-to-have)."""
        if not text:
            return []
        added = []
        for marker in ["加分", "优先", "preferred"]:
            idx = text.find(marker)
            if idx >= 0:
                chunk = text[idx:idx + 200]
                added.extend(re.findall(r"(\w{2,8})", chunk))
        return list(dict.fromkeys(added))[:10]
