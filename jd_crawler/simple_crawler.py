"""
JD Crawler - JobsDB with dedup + SQLite + Multi-keyword + Multi-page + 7-day filter
"""
import sys
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List

# 添加项目根目录
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(Path(__file__).parent))

import asyncio
from loguru import logger

from tools.scraper.jobsdb_scraper import JobsDBScraper
from database.jd_db import JDDatabase


# 默认关键词
DEFAULT_KEYWORDS = [
    "AI Product Manager",
    "AI PM",
    "Product Manager AI",
    "AI Product",
    "Artificial Intelligence",
    "AI ML",
    "Machine Learning",
]

# 每页搜索的最大页数（设置一个较大的值，由 max-jobs 控制实际停止）
MAX_PAGES_PER_KEYWORD = 10


def normalize_url(url: str) -> str:
    """规范化 URL：只保留 /job/XXXXX 部分，去掉 query 参数和 hash"""
    match = re.search(r'(https?://[^/]+/job/\d+)', url)
    if match:
        return match.group(1)
    return url.split('?')[0].split('#')[0]


def extract_company(raw_text: str) -> str:
    """从 raw_text 提取公司名"""
    if not raw_text:
        return ""
    lines = raw_text.split('\n')
    for i, line in enumerate(lines):
        line = line.strip()
        if line == "View all jobs" and i > 0:
            # "View all jobs" 的上一行是公司名
            return lines[i-1].strip()
    return ""


def extract_title(raw_text: str) -> str:
    """从 raw_text 提取真实职位标题"""
    if not raw_text:
        return ""
    lines = raw_text.split('\n')
    for i, line in enumerate(lines):
        line = line.strip()
        if line == "View all jobs" and i > 1:
            # "View all jobs" 的上两行是标题
            return lines[i-2].strip()
    # fallback：找前几个有长度的行
    for line in lines:
        line = line.strip()
        if line and len(line) > 5 and len(line) < 100:
            return line
    return ""


def extract_days_old(raw_text: str) -> Optional[int]:
    """
    从 raw_text 提取发布天数
    - "Posted 1d ago" → 1
    - "Posted 7d ago" → 7
    - "Posted 30d+ ago" → 30
    - "Posted yesterday" → 1
    - "Posted today" → 0
    - "Posted 2w ago" → 14 (超过7天)
    """
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

    # fallback：找类似 3d, 2d 的模式
    match = re.search(r'(\d+)d\+?\s+ago', raw_text.lower())
    if match:
        return int(match.group(1))

    return None


def days_to_posted_within(days: int) -> Optional[int]:
    """
    将天数转换为 JobsDB 的 daterange 参数
    JobsDB 只支持：1, 3, 7, 14, 30
    """
    if days <= 0:
        return None  # anytime
    elif days <= 1:
        return 1
    elif days <= 3:
        return 3
    elif days <= 7:
        return 7
    elif days <= 14:
        return 14
    elif days <= 30:
        return 30
    return None


def is_relevant(title: str, raw_text: str) -> bool:
    """
    暂时不过滤，先测试爬虫能否正常工作
    """
    return True


import argparse


async def main():
    print("=" * 60)
    print("JobHunter - JD Crawler")
    print("=" * 60)

    parser = argparse.ArgumentParser(description="JobsDB 爬虫")
    parser.add_argument("--keywords", type=str, nargs="+", default=DEFAULT_KEYWORDS,
                        help="搜索关键词（多个关键词用空格分隔）")
    parser.add_argument("--time", type=str, choices=["3", "7", "14", "30", "any"], default="7",
                        help="发布时间范围：3=3天, 7=7天, 14=14天, 30=30天, any=任何时间")
    parser.add_argument("--max-jobs", type=int, default=50, help="最多爬取多少个职位")
    parser.add_argument("--speed", type=float, default=0.5, help="Human speed (0.3-2.0)")
    args = parser.parse_args()

    # 解析时间参数
    if args.time == "any":
        max_days = 0
        posted_within = None
        time_label = "any time"
    else:
        max_days = int(args.time)
        posted_within = max_days
        time_label = f"{max_days} days"

    # 初始化数据库
    db = JDDatabase()
    initial_count = db.get_count()

    print(f"\nKeywords: {', '.join(args.keywords)}")
    print(f"Time range: {time_label}")
    print(f"Max jobs: {args.max_jobs}")
    print(f"Human speed: {args.speed}x")
    print(f"Database: {db.get_count()} JDs already stored")
    print("\nStarting crawler... (press Ctrl+C to stop)\n")

    crawled_count = 0
    skipped_count = 0
    filtered_count = 0
    old_count = 0

    # 记录已处理的URL，避免重复访问
    seen_urls = set()

    try:
        async with JobsDBScraper(headless=False, human_speed=args.speed) as scraper:

            # 遍历所有关键词
            for keyword in args.keywords:
                if crawled_count >= args.max_jobs:
                    break

                logger.info(f"Searching keyword: {keyword}")

                # 遍历多页（最多 MAX_PAGES_PER_KEYWORD 页，由 max-jobs 控制实际停止）
                for page in range(1, MAX_PAGES_PER_KEYWORD + 1):
                    if crawled_count >= args.max_jobs:
                        break

                    logger.info(f"Searching page {page} for '{keyword}'")

                    # 使用 JobsDB 原生的 daterange 参数在搜索时过滤
                    jobs = await scraper.search_jobs(keyword=keyword, page=page, posted_within=posted_within)
                    logger.info(f"Found {len(jobs)} job listings on page {page}")

                    # 遍历搜索结果
                    for i, job in enumerate(jobs):
                        if crawled_count >= args.max_jobs:
                            break

                        raw_url = job.get("url", "")
                        if not raw_url:
                            continue

                        # 规范化 URL 去重
                        url = normalize_url(raw_url)

                        # 检查是否已经处理过（内存或数据库）
                        if url in seen_urls:
                            continue
                        if db.exists(url):
                            skipped_count += 1
                            logger.debug(f"  Skipped (duplicate): {url}")
                            continue

                        seen_urls.add(url)

                        title = job.get("title", "")
                        description = job.get("description", "")

                        try:
                            job_detail = await scraper.get_job_detail(raw_url)

                            # 从 raw_text 提取真实标题和日期
                            raw_text = job_detail.get("raw_text", "")
                            real_title = extract_title(raw_text)
                            if real_title:
                                title = real_title

                            days_old = extract_days_old(raw_text)

                            # 如果指定了时间范围，做二次检查
                            if max_days > 0 and days_old is not None and days_old > max_days:
                                old_count += 1
                                logger.debug(f"  Skipped (too old, {days_old}d): {title[:50]}")
                                continue

                            job_detail["title"] = title
                            job_detail["url"] = url
                            job_detail["company"] = extract_company(raw_text)
                            job_detail["crawled_at"] = datetime.now().isoformat()
                            job_detail["source"] = "jobsdb"
                            job_detail["search_keyword"] = keyword
                            job_detail["days_old"] = days_old

                            # 用完整 raw_text 做智能过滤
                            if not is_relevant(title, raw_text):
                                filtered_count += 1
                                logger.debug(f"  Filtered (not relevant): {title[:50]}")
                                continue

                            days_str = f"{days_old}d old" if days_old is not None else "unknown age"
                            logger.info(f"  [{crawled_count + 1}/{args.max_jobs}] {title[:50]} ({days_str})")

                            # 存入数据库
                            db.insert(job_detail)
                            crawled_count += 1

                        except Exception as e:
                            logger.error(f"  Failed to crawl {url}: {e}")

            # 显示统计
            final_count = db.get_count()
            print(f"\n{'='*60}")
            print(f"Done!")
            print(f"  Newly crawled: {crawled_count}")
            print(f"  Skipped (duplicate): {skipped_count}")
            print(f"  Filtered (not relevant): {filtered_count}")
            print(f"  Skipped (too old): {old_count}")
            print(f"  Total in DB: {final_count}")
            print(f"{'='*60}")

    except KeyboardInterrupt:
        print(f"\n\nCrawling stopped by user")
        print(f"Total in DB: {db.get_count()}")

    except Exception as e:
        logger.exception(f"Crawler failed: {e}")


if __name__ == "__main__":
    asyncio.run(main())
