"""批量从前程无忧（51job）抓取多关键词 JD 并落库。

设计沿用 batch_liepin.py 的套路：搜索→解析→入库。

**安全注意**：
- 51job 移动 API 无需登录，但有频率限制
- 每请求间隔 3-6s（正态分布），每天上限 200 条/关键词
- 触发 403/429 时自动暂停 30 分钟，不强行重试
- 不尝试突破登录墙，不爬需认证的详情页

用法：
    # 冒烟：单关键词 10 条
    python scripts/collectors/batch_51job.py --keyword "AI产品经理" --per-keyword 10

    # 正式：内置 30 个关键词，每词 20 条 ≈ 600 条
    python scripts/collectors/batch_51job.py --default-keywords --per-keyword 20

    # 指定城市
    python scripts/collectors/batch_51job.py --keyword "Java工程师" --city "上海" --per-keyword 20
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from database.factory import get_db
from services.jd_library_service import is_garbage_jd
from tools.scraper.fiftyonejob_scraper import FiftyOneJobScraper


# 内置 30 个中高端关键词（与猎聘对齐，方便对比数据来源）
DEFAULT_KEYWORDS = [
    # AI / 数据
    "AI产品经理", "算法工程师", "机器学习工程师", "数据科学家",
    "大模型工程师", "NLP工程师",
    # 产品
    "产品经理", "高级产品经理", "产品总监", "产品运营",
    # 技术
    "Java工程师", "Python开发", "前端工程师", "全栈工程师",
    "架构师", "技术总监", "DevOps工程师",
    # 数据分析
    "数据分析师", "商业分析师", "数据工程师",
    # 运营 / 市场
    "用户增长", "增长黑客", "运营经理", "市场总监",
    # 金融
    "量化研究员", "投资经理", "风控经理",
    # 其他高薪
    "HRBP", "项目经理", "供应链总监",
]


def _normalize_51job_url(raw: str) -> str:
    """规范化 51job URL。"""
    if not raw:
        return ""
    m = re.match(r"(https?://jobs\.51job\.com/\d+\.html)", raw)
    return m.group(1) if m else raw


def _map_to_jd_row(job: Dict[str, Any], keyword: str) -> Dict[str, Any]:
    """FiftyOneJobScraper 返回的 dict → jds 表 schema。"""
    raw_text = job.get("raw_text") or job.get("description") or ""
    url = _normalize_51job_url(job.get("url") or "")
    return {
        "url": url or f"51job://unknown/{hash(raw_text)}",
        "title": job.get("title") or "",
        "company": job.get("company") or "",
        "location": job.get("location") or "全国",
        "salary_str": job.get("salary_range") or "",
        "raw_text": raw_text,
        "source": "51job_batch",
        "search_keyword": keyword,
        "platform": "51job",
        "language": "zh",
        "industry_tag": None,
        "function_tag": None,
        "position_tag": None,
        "auto_classified": 0,
        "is_public": 0,
    }


async def crawl_one_keyword(
    scraper: FiftyOneJobScraper,
    keyword: str,
    per_keyword: int,
    location: Optional[str],
    db,
) -> Dict[str, int]:
    stats = {"fetched": 0, "inserted": 0, "skipped": 0, "failed": 0}
    logger.info(f"[{keyword}] search start, target={per_keyword}, location={location}")

    page = 1
    fetched = 0

    while fetched < per_keyword:
        page_size = min(per_keyword - fetched, 20)
        try:
            jobs = await scraper.search_jobs(
                keyword=keyword,
                location=location,
                page=page,
                limit=page_size,
            )
        except Exception as exc:
            logger.error(f"[{keyword}] search_jobs failed: {exc}")
            stats["failed"] = per_keyword - fetched
            break

        if not jobs:
            logger.info(f"[{keyword}] page={page} no results, stopping")
            break

        for job in jobs:
            job_url = job.get("url")
            if not job_url:
                stats["skipped"] += 1
                continue

            row = _map_to_jd_row(job, keyword)
            if is_garbage_jd(row):
                logger.warning(f"[{keyword}] skipped garbage JD: {job_url}")
                stats["skipped"] += 1
                continue

            try:
                db.insert_jd(row)
                stats["inserted"] += 1
                stats["fetched"] += 1
            except Exception as exc:
                # 可能是唯一索引冲突（重复 JD），跳过
                if "UNIQUE" in str(exc).upper() or "duplicate" in str(exc).lower():
                    stats["skipped"] += 1
                else:
                    logger.warning(f"[{keyword}] insert_jd failed: {exc}")
                    stats["skipped"] += 1

            fetched += 1
            if fetched >= per_keyword:
                break

        logger.info(f"[{keyword}] page={page} got {len(jobs)} jobs, total fetched={fetched}")
        page += 1

        # 51job 对频繁翻页更敏感，每页间隔更长
        if len(jobs) >= 20:
            await asyncio.sleep(5)

    logger.info(f"[{keyword}] done: {stats}")
    return stats


async def run(
    keywords: List[str],
    per_keyword: int,
    location: Optional[str],
    request_interval_min: float = 3.0,
    request_interval_max: float = 6.0,
) -> Dict[str, int]:
    db = get_db()
    total = {"fetched": 0, "inserted": 0, "skipped": 0, "failed": 0}

    scraper = FiftyOneJobScraper(
        request_interval_min=request_interval_min,
        request_interval_max=request_interval_max,
    )

    try:
        for i, kw in enumerate(keywords):
            stats = await crawl_one_keyword(scraper, kw, per_keyword, location, db)
            for k in total:
                total[k] += stats[k]

            # 每关键词之间稍作休息
            if i < len(keywords) - 1:
                await asyncio.sleep(2)

            logger.info(f"[batch] progress {i+1}/{len(keywords)}: total={total}")
    finally:
        await scraper.close()

    return total


def _load_keywords(args) -> List[str]:
    if args.keywords_file:
        path = Path(args.keywords_file)
        if not path.exists():
            logger.error(f"keywords file not found: {path}")
            sys.exit(2)
        kws = [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]
        return kws or DEFAULT_KEYWORDS
    if args.default_keywords:
        return DEFAULT_KEYWORDS
    if args.keyword:
        return [args.keyword]
    return DEFAULT_KEYWORDS


def main():
    parser = argparse.ArgumentParser(
        description="Batch crawl 51job (前程无忧) and insert into jds table"
    )
    parser.add_argument("--keyword", help="单关键词（冒烟用）")
    parser.add_argument("--keywords-file", help="多关键词文件，每行一个")
    parser.add_argument("--default-keywords", action="store_true", help="用内置 30 个中文关键词")
    parser.add_argument("--per-keyword", type=int, default=20, help="每词抓多少条（默认 20）")
    parser.add_argument("--city", help="城市，如 上海 / 深圳（默认全国）")
    parser.add_argument(
        "--interval-min", type=float, default=3.0,
        help="请求间隔最小秒数（默认 3.0）",
    )
    parser.add_argument(
        "--interval-max", type=float, default=6.0,
        help="请求间隔最大秒数（默认 6.0）",
    )
    args = parser.parse_args()

    keywords = _load_keywords(args)
    logger.info(
        f"keywords={len(keywords)}个  per_keyword={args.per_keyword}  "
        f"location={args.city}  interval=[{args.interval_min},{args.interval_max}]s"
    )

    total = asyncio.run(
        run(
            keywords,
            args.per_keyword,
            location=args.city,
            request_interval_min=args.interval_min,
            request_interval_max=args.interval_max,
        )
    )

    print("\n=== 51job Batch Crawl Result ===")
    print(f"  Keywords run:    {len(keywords)}")
    print(f"  Total fetched:   {total['fetched']}")
    print(f"  Inserted:        {total['inserted']}")
    print(f"  Skipped (dup):   {total['skipped']}")
    print(f"  Failed:          {total['failed']}")


if __name__ == "__main__":
    main()
