# -*- coding: utf-8 -*-
"""Pipeline: crawl → clean → classify → insert into database.

Orchestrates the full flow:
  1. Fetch raw JDs from a crawler site (e.g. BossCrawler).
  2. Clean / normalize fields.
  3. Run Classifier.classify() for industry/function/position tags.
  4. Upsert via get_db().insert_jd() with source_url dedup.
"""

import asyncio
from typing import Any, Dict, List, Optional

from loguru import logger

from crawler.base_crawler import BaseCrawler
from database.classifier import Classifier
from database.factory import get_db


class CrawlPipeline:
    """End-to-end pipeline from job-site crawling to database insertion."""

    def __init__(self, crawler: BaseCrawler, classifier: Optional[Classifier] = None):
        self.crawler = crawler
        self.classifier = classifier or Classifier()
        self.db = get_db()
        self._inserted = 0
        self._skipped_dedup = 0

    def run(self, keyword: str, limit: int = 20, city: str = "101010100") -> Dict[str, int]:
        """Execute the full pipeline for a single keyword.

        Wraps the async ``_run_async`` in ``asyncio.run()`` so callers
        (including ``run_crawler.py``) never need to be async themselves.

        Args:
            keyword: Search keyword (e.g. "AI产品经理").
            limit: Max JDs to fetch and insert.
            city: City code (passed to crawler, site-specific).

        Returns:
            Dict with counts: inserted, skipped, total_fetched.
        """
        return asyncio.run(self._run_async(keyword, limit, city))

    async def _run_async(self, keyword: str, limit: int, city: str) -> Dict[str, int]:
        """Actual async pipeline logic."""
        logger.info(f"[Pipeline] Starting crawl for keyword='{keyword}', limit={limit}")

        # Fetch raw jobs from the site (async IO)
        raw_jobs = await self.crawler.fetch_jobs(keyword=keyword, city=city, page=1, limit=limit)
        if not raw_jobs:
            logger.warning(f"[Pipeline] No jobs fetched for '{keyword}'")
            return {"inserted": 0, "skipped": 0, "total_fetched": 0}

        total_fetched = len(raw_jobs)
        logger.info(f"[Pipeline] Fetched {total_fetched} raw jobs")

        for job in raw_jobs:
            self._process_one(job)

        logger.info(
            f"[Pipeline] Done: inserted={self._inserted}, "
            f"skipped_dedup={self._skipped_dedup}, total={total_fetched}"
        )
        return {
            "inserted": self._inserted,
            "skipped": self._skipped_dedup,
            "total_fetched": total_fetched,
        }

    def _process_one(self, job: Dict[str, Any]) -> None:
        """Clean, classify, and insert a single JD."""
        url = job.get("source_url", "")
        if not url:
            logger.warning("[Pipeline] Skipping job with empty source_url")
            return

        # Dedup: check if URL already exists
        existing = self.db.get_jd_by_url(url)
        if existing:
            self._skipped_dedup += 1
            logger.debug(f"[Pipeline] Skipped (duplicate URL): {url}")
            return

        # Normalize fields
        cleaned = self._clean(job)

        # Auto-classify
        try:
            classification = self.classifier.classify(
                title=cleaned["title"],
                raw_text=cleaned.get("raw_text", ""),
            )
            cleaned["industry_tag"] = classification.get("industry_tag")
            cleaned["function_tag"] = classification.get("function_tag")
            cleaned["position_tag"] = classification.get("position_tag")
            cleaned["auto_classified"] = 1
            layer = classification.get("layer", "?")
            logger.debug(f"[Pipeline] Classified as layer {layer}: "
                         f"industry={cleaned['industry_tag']}, "
                         f"function={cleaned['function_tag']}, "
                         f"position={cleaned['position_tag']}")
        except Exception as exc:
            logger.warning(f"[Pipeline] Classification failed: {exc}")

        # Insert into DB
        try:
            jd_id = self.db.insert_jd(cleaned)
            self._inserted += 1
            logger.info(f"[Pipeline] Inserted JD #{self._inserted}: "
                        f"'{cleaned['title']}' @ {cleaned['company']} (id={jd_id})")
        except Exception as exc:
            logger.error(f"[Pipeline] Failed to insert JD: {exc}")
            return

        # v2.1 M3.4: JD 入库后语义切分 + 向量化
        try:
            from tools.jd_indexer import embed_and_store_jd_chunks
            embed_and_store_jd_chunks(self.db, jd_id, cleaned.get("raw_text", ""))
        except Exception as exc:
            logger.warning(f"[Pipeline] Indexing failed for {jd_id}: {exc}")

    @staticmethod
    def _clean(job: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize raw job data into the format expected by insert_jd()."""
        now = job.get("crawled_at")
        return {
            "url": job.get("source_url", ""),
            "title": str(job.get("title", "")).strip(),
            "company": str(job.get("company", "")).strip(),
            "location": str(job.get("location", "")).strip(),
            "salary_str": job.get("salary_str"),
            "skills_required": job.get("skills_required", []),
            "skills_nice": job.get("skills_nice", []),
            "experience_level": job.get("experience_level", ""),
            "education": job.get("education", ""),
            "raw_text": str(job.get("raw_text", ""))[:10000],
            "platform": job.get("platform", ""),
            "search_keyword": job.get("search_keyword", ""),
            "source": "crawler",
            "crawled_at": now,
            # These will be filled by the pipeline:
            "industry_tag": None,
            "function_tag": None,
            "position_tag": None,
            "auto_classified": 0,
        }
