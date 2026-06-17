
"""
调试版爬虫：不做严格过滤，先看看有什么
"""
import sys
import re
from pathlib import Path
from datetime import datetime
from typing import Optional

# 添加项目根目录
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(Path(__file__).parent))

import asyncio
from loguru import logger

from tools.scraper.jobsdb_scraper import JobsDBScraper
from database.jd_db import JDDatabase

# 更宽泛的关键词
KEYWORDS = [
    "AI",
    "Artificial Intelligence",
    "Machine Learning",
    "Data Scientist",
    "ML",
    "LLM"
]

MAX_PAGES = 2

def normalize_url(url: str) -> str:
    match = re.search(r'(https?://[^/]+/job/\d+)', url)
    if match:
        return match.group(1)
    return url.split('?')[0].split('#')[0]

def extract_title(raw_text: str) -> str:
    if not raw_text:
        return ""
    lines = raw_text.split('\n')
    for i, line in enumerate(lines):
        line = line.strip()
        if line == "View all jobs" and i > 1:
            return lines[i-2].strip()
    for line in lines:
        line = line.strip()
        if line and len(line) > 5 and len(line) < 100:
            return line
    return ""

def extract_company(raw_text: str) -> str:
    if not raw_text:
        return ""
    lines = raw_text.split('\n')
    for i, line in enumerate(lines):
        line = line.strip()
        if line == "View all jobs" and i > 0:
            return lines[i-1].strip()
    return ""

def extract_days_old(raw_text: str) -> Optional[int]:
    if not raw_text:
        return None
    match = re.search(r'Posted (\d+)d\+? ago', raw_text)
    if match:
        return int(match.group(1))
    match = re.search(r'Posted (\d+)w ago', raw_text)
    if match:
        return int(match.group(1)) * 7
    if "Posted yesterday" in raw_text:
        return 1
    if "Posted today" in raw_text:
        return 0
    return None

async def main():
    print("=" * 60)
    print("调试版爬虫 - 只去重不严格过滤")
    print("=" * 60)

    db = JDDatabase()

    print(f"Initial DB: {db.get_count()} JDs already stored")

    crawled_count = 0
    skipped_count = 0
    seen_urls = set()

    try:
        async with JobsDBScraper(headless=False, human_speed=0.8) as scraper:
            for keyword in KEYWORDS:
                if crawled_count >= 30:
                    break

                logger.info(f"Searching keyword: {keyword}")

                for page in range(1, MAX_PAGES + 1):
                    if crawled_count >= 30:
                        break

                    logger.info(f"Searching page {page} for '{keyword}'")

                    jobs = await scraper.search_jobs(keyword=keyword, page=page)
                    logger.info(f"Found {len(jobs)} job listings on page {page}")

                    for i, job in enumerate(jobs):
                        if crawled_count >= 30:
                            break

                        raw_url = job.get("url", "")
                        if not raw_url:
                            continue

                        url = normalize_url(raw_url)

                        if url in seen_urls:
                            continue
                        if db.exists(url):
                            skipped_count += 1
                            continue

                        seen_urls.add(url)

                        title = job.get("title", "")

                        try:
                            job_detail = await scraper.get_job_detail(raw_url)

                            raw_text = job_detail.get("raw_text", "")

                            real_title = extract_title(raw_text)
                            if real_title:
                                title = real_title

                            days_old = extract_days_old(raw_text)

                            job_detail["title"] = title
                            job_detail["url"] = url
                            job_detail["company"] = extract_company(raw_text)
                            job_detail["crawled_at"] = datetime.now().isoformat()
                            job_detail["source"] = "jobsdb"
                            job_detail["search_keyword"] = keyword
                            job_detail["days_old"] = days_old

                            days_str = f"{days_old}d old" if days_old is not None else "unknown age"
                            logger.info(f"  [{crawled_count + 1}] {title[:50]} ({days_str})")

                            db.insert(job_detail)
                            crawled_count += 1

                        except Exception as e:
                            logger.error(f"  Failed to crawl {url}: {e}")

            final_count = db.get_count()
            print(f"\n{'='*60}")
            print(f"Done!")
            print(f"  Newly crawled: {crawled_count}")
            print(f"  Skipped (duplicate): {skipped_count}")
            print(f"  Total in DB: {final_count}")
            print(f"{'='*60}")

    except KeyboardInterrupt:
        print(f"\n\nCrawling stopped by user")
        print(f"Total in DB: {db.get_count()}")

    except Exception as e:
        logger.exception(f"Crawler failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())
