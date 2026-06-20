"""批量从 JobsDB 抓取多关键词 JD 并直接落库。

设计动机：
- crawler/run_crawler.py 的 jobsdb 适配器未实现（SUPPORTED_SITES 里是空字符串），
  但 tools/scraper/jobsdb_scraper.py 的 search_jobs / get_job_detail 接口完整可用。
  本脚本绕开 crawler 框架，直接调底层 scraper，省一层适配。
- 默认小样模式（1 关键词 × 10 条）用于冒烟；跑通后 --keywords-file + --per-keyword 放大。

用法：
    # 冒烟：单关键词抓 10 条
    python scripts/collectors/batch_jobsdb.py --keyword "Product Manager" --per-keyword 10

    # 正式：多关键词循环
    python scripts/collectors/batch_jobsdb.py \
        --keywords-file scripts/collectors/jobsdb_keywords.txt \
        --per-keyword 50

    # 指定数据库（默认走 .env 的 DATABASE_URL）
    DATABASE_URL=sqlite:///data/jobhunter_v2.db python scripts/collectors/batch_jobsdb.py ...
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from database.factory import get_db
from tools.scraper.jobsdb_scraper import JobsDBScraper


DEFAULT_KEYWORDS = [
    "Product Manager",
    "Data Scientist",
    "Software Engineer",
    "AI Engineer",
    "DevOps Engineer",
    "UX Designer",
    "Business Analyst",
    "Project Manager",
    "Marketing Manager",
    "Finance Manager",
]


def _normalize_jobsdb_url(raw: str) -> str:
    """规范化 JobsDB URL：只保留 /job/XXXXX，去掉 query / fragment。

    JobsDB 搜索结果里同一职位会出现多次，URL 的 query 参数不同
   （ref= / origin= / sol= 等），导致 (url, user_id) 唯一约束失效，
    同一条 JD 被重复入库。规范化后才能正确去重。
    """
    if not raw:
        return ""
    m = re.match(r"(https://hk\.jobsdb\.com/job/\d+)", raw)
    return m.group(1) if m else raw


def _map_to_jd_row(job: Dict[str, Any], keyword: str) -> Dict[str, Any]:
    """把 JobsDBScraper.parse_job 返回的 dict 映射到 jds schema。"""
    raw_text = job.get("raw_text") or job.get("description") or ""
    title = job.get("title") or ""
    company = job.get("company") or ""
    location = job.get("location") or "Hong Kong"
    salary_str = job.get("salary_range") or job.get("salary") or ""
    url = _normalize_jobsdb_url(job.get("url") or job.get("job_url") or "")

    # salary_min/max 留空，让 repository 层不强制；JobsDB 薪资格式杂，不强解析
    return {
        "url": url or f"jobsdb://unknown/{hash(raw_text)}",
        "title": title,
        "company": company,
        "location": location,
        "salary_str": salary_str,
        "raw_text": raw_text,
        "source": "jobsdb_batch",
        "search_keyword": keyword,
        "platform": "jobsdb",
        "language": "en",
        "industry_tag": None,
        "function_tag": None,
        "position_tag": None,
        "auto_classified": 0,
        "is_public": 0,
    }


async def crawl_one_keyword(
    scraper: JobsDBScraper,
    keyword: str,
    per_keyword: int,
    db,
) -> Dict[str, int]:
    """抓单关键词的 per_keyword 条 JD，逐条落库。返回计数。"""
    stats = {"fetched": 0, "inserted": 0, "skipped": 0, "failed": 0}
    logger.info(f"[{keyword}] search start, target={per_keyword}")

    try:
        jobs = await scraper.search_jobs(keyword=keyword)
    except Exception as exc:
        logger.error(f"[{keyword}] search_jobs failed: {exc}")
        stats["failed"] = per_keyword
        return stats

    logger.info(f"[{keyword}] search returned {len(jobs)} job cards")

    for job in jobs[:per_keyword]:
        job_url = job.get("url") or job.get("job_url")
        if not job_url:
            stats["skipped"] += 1
            continue

        try:
            detail = await scraper.get_job_detail(job_url)
        except Exception as exc:
            logger.warning(f"[{keyword}] get_job_detail failed for {job_url}: {exc}")
            stats["failed"] += 1
            continue

        if not detail or not (detail.get("raw_text") or detail.get("description")):
            stats["skipped"] += 1
            continue

        row = _map_to_jd_row(detail, keyword)
        try:
            # insert_jd 用 INSERT OR IGNORE，重复 URL 静默跳过；
            # 返回值不区分真插入 vs 被忽略，所以 inserted 计数会偏高。
            # 数据正确性由 DB UNIQUE(url, user_id) 保证，统计仅作参考。
            db.insert_jd(row)
            stats["inserted"] += 1
            stats["fetched"] += 1
        except Exception as exc:
            logger.warning(f"[{keyword}] insert_jd failed: {exc}")
            stats["skipped"] += 1

        # 礼貌延迟由 scraper 内部 rate_limiter 管，这里不额外 sleep

    logger.info(f"[{keyword}] done: {stats}")
    return stats


async def run(keywords: List[str], per_keyword: int, headless: bool) -> Dict[str, int]:
    db = get_db()
    total = {"fetched": 0, "inserted": 0, "skipped": 0, "failed": 0}

    scraper = JobsDBScraper(headless=headless)
    try:
        for kw in keywords:
            stats = await crawl_one_keyword(scraper, kw, per_keyword, db)
            for k in total:
                total[k] += stats[k]
    finally:
        try:
            await scraper.close()
        except Exception:
            pass

    return total


def _load_keywords(args) -> List[str]:
    if args.keywords_file:
        path = Path(args.keywords_file)
        if not path.exists():
            logger.error(f"keywords file not found: {path}")
            sys.exit(2)
        kws = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]
        return kws or DEFAULT_KEYWORDS
    if args.keyword:
        return [args.keyword]
    return DEFAULT_KEYWORDS


def main():
    parser = argparse.ArgumentParser(description="Batch crawl JobsDB HK and insert into jds table")
    parser.add_argument("--keyword", help="单关键词（冒烟用）")
    parser.add_argument("--keywords-file", help="多关键词文件，每行一个")
    parser.add_argument("--per-keyword", type=int, default=10, help="每个关键词抓多少条（默认 10）")
    parser.add_argument("--no-headless", action="store_true", help="显示浏览器窗口（调试用，默认 headless）")
    args = parser.parse_args()

    keywords = _load_keywords(args)
    logger.info(f"keywords={keywords}  per_keyword={args.per_keyword}  headless={not args.no_headless}")

    total = asyncio.run(run(keywords, args.per_keyword, headless=not args.no_headless))

    print("\n=== Batch Crawl Result ===")
    print(f"  Keywords run:    {len(keywords)}")
    print(f"  Total fetched:   {total['fetched']}")
    print(f"  Inserted:        {total['inserted']}")
    print(f"  Skipped (dup):   {total['skipped']}")
    print(f"  Failed:          {total['failed']}")


if __name__ == "__main__":
    main()
