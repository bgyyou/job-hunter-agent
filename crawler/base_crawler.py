# -*- coding: utf-8 -*-
"""Base crawler with request masking, random delay, rate-limit handling, and logging."""

import asyncio
import random
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse

from fake_useragent import UserAgent
from httpx import AsyncClient, Timeout, HTTPStatusError, RequestError
from loguru import logger
from pydantic_settings import BaseSettings


class CrawlerSettings(BaseSettings):
    """Crawl-specific settings, reads from .env."""

    rate_limit_min: float = 2.0
    rate_limit_max: float = 5.0
    daily_limit: int = 200
    blocked_timeout_minutes: int = 30
    max_retries: int = 3
    timeout: int = 30
    concurrent_domains: int = 3

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


class DomainRateLimiter:
    """Track per-domain rate limits. Auto-unblock after blocked_timeout."""

    def __init__(self, timeout_minutes: int = 30):
        self._blocked: Dict[str, datetime] = {}
        self._timeout = timedelta(minutes=timeout_minutes)

    def is_blocked(self, domain: str) -> bool:
        if domain in self._blocked:
            if datetime.now() < self._blocked[domain]:
                return True
            del self._blocked[domain]
        return False

    def mark_blocked(self, domain: str) -> None:
        self._blocked[domain] = datetime.now() + self._timeout
        logger.warning(f"Domain {domain} rate-limited for {self._timeout}")

    @property
    def active_blocks(self) -> int:
        return len(self._blocked)


class BaseCrawler:
    """Shared crawler foundation: UA rotation, random delay, retry, rate-limit.

    Subclasses implement ``fetch_jobs(keyword: str, limit: int) -> List[Dict]``.
    """

    def __init__(self, settings: Optional[CrawlerSettings] = None):
        self.settings = settings or CrawlerSettings()
        try:
            self._ua = UserAgent()
        except Exception:
            # Fallback if fake-useragent cache is broken
            self._ua = UserAgent(strict=True)
        self._domain_limiter = DomainRateLimiter(self.settings.blocked_timeout_minutes)
        self._daily_count = 0
        self._client: Optional[AsyncClient] = None

    def _headers(self) -> Dict[str, str]:
        try:
            ua_str = self._ua.random
        except Exception:
            ua_str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _headers(self) -> Dict[str, str]:
        return {
            "User-Agent": self._ua.random,
            "Accept": "text/html,application/json,application/xhtml+xml,*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }

    def _base_url(self) -> str:
        """Override in subclass. Return the site root URL."""
        raise NotImplementedError

    @property
    def _domain(self) -> str:
        return urlparse(self._base_url()).netloc

    async def _ensure_client(self) -> AsyncClient:
        if self._client is None or self._client.is_closed:
            timeout = Timeout(self.settings.timeout)
            self._client = AsyncClient(timeout=timeout, follow_redirects=True)
        return self._client

    async def get(
        self, url: str, params: Optional[Dict] = None, json_response: bool = False
    ) -> Optional[Any]:
        """GET with retry, rate-limit detection, and random jitter."""
        domain = urlparse(url).netloc
        if self._domain_limiter.is_blocked(domain):
            logger.warning(f"[{self.__class__.__name__}] {domain} is blocked, skipping {url}")
            return None

        client = await self._ensure_client()
        headers = self._headers()

        for attempt in range(1, self.settings.max_retries + 1):
            try:
                resp = await client.get(url, params=params, headers=headers)

                if resp.status_code == 429 or resp.status_code == 403:
                    logger.warning(
                        f"[{self.__class__.__name__}] {domain} returned {resp.status_code} "
                        f"(attempt {attempt}/{self.settings.max_retries})"
                    )
                    self._domain_limiter.mark_blocked(domain)
                    return None

                resp.raise_for_status()

                self._apply_delay()
                return resp.json() if json_response else resp.text

            except HTTPStatusError as exc:
                logger.warning(
                    f"[{self.__class__.__name__}] HTTP error {exc.response.status_code} "
                    f"for {url} (attempt {attempt}/{self.settings.max_retries})"
                )
                if exc.response.status_code in (403, 429):
                    self._domain_limiter.mark_blocked(domain)
                    return None
                await self._retry_wait(attempt)

            except RequestError as exc:
                logger.warning(f"[{self.__class__.__name__}] Request error: {exc} (attempt {attempt})")
                await self._retry_wait(attempt)

        logger.error(f"[{self.__class__.__name__}] Failed after {self.settings.max_retries} retries: {url}")
        return None

    async def post(
        self,
        url: str,
        data: Optional[Dict] = None,
        json: Optional[Dict] = None,
        json_response: bool = False,
    ) -> Optional[Any]:
        """POST with same retry/delay logic."""
        domain = urlparse(url).netloc
        if self._domain_limiter.is_blocked(domain):
            return None

        client = await self._ensure_client()
        headers = self._headers()

        for attempt in range(1, self.settings.max_retries + 1):
            try:
                resp = await client.post(url, data=data, json=json, headers=headers)

                if resp.status_code in (403, 429):
                    self._domain_limiter.mark_blocked(domain)
                    return None

                resp.raise_for_status()
                self._apply_delay()
                return resp.json() if json_response else resp.text

            except Exception as exc:
                logger.warning(f"[{self.__class__.__name__}] POST error (attempt {attempt}): {exc}")
                await self._retry_wait(attempt)

        return None

    # ------------------------------------------------------------------
    # Delay & rate limiting
    # ------------------------------------------------------------------

    def _apply_delay(self) -> None:
        """Random delay between requests to respect rate limits."""
        delay = random.uniform(self.settings.rate_limit_min, self.settings.rate_limit_max)
        logger.debug(f"[{self.__class__.__name__}] Waiting {delay:.1f}s ...")
        time.sleep(delay)

    async def _retry_wait(self, attempt: int) -> None:
        """Exponential backoff between retries."""
        wait = min(2 ** attempt, 30)
        logger.info(f"[{self.__class__.__name__}] Retrying in {wait}s ...")
        await asyncio.sleep(wait)

    # ------------------------------------------------------------------
    # Daily quota
    # ------------------------------------------------------------------

    def can_fetch(self) -> bool:
        return self._daily_count < self.settings.daily_limit

    def increment_count(self, n: int = 1) -> None:
        self._daily_count += n

    @property
    def daily_remaining(self) -> int:
        return max(0, self.settings.daily_limit - self._daily_count)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def __del__(self):
        pass  # Async cleanup on __del__ is unreliable during interpreter shutdown
