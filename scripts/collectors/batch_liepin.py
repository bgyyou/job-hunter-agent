"""批量从猎聘抓取多关键词 JD 并落库。

设计沿用 batch_jobsdb.py 的套路：搜索→详情→入库，每 batch_size 个关键词
重启一次 Playwright 避免 Edge driver 连接断（v2.1 N9 教训）。

**前置条件**：必须先跑 `python scripts/collectors/login_liepin.py` 完成猎聘登录，
登录态会持久化到 data/browser_profiles/liepin/，本脚本复用该 profile。

用法：
    # 冒烟：单关键词 10 条
    python scripts/collectors/batch_liepin.py --keyword "AI产品经理" --per-keyword 10

    # 正式：内置 30 个中高端中文关键词，每词 10 条 ≈ 300 条
    python scripts/collectors/batch_liepin.py --default-keywords --per-keyword 10

    # 指定文件
    python scripts/collectors/batch_liepin.py \\
        --keywords-file scripts/collectors/liepin_keywords.txt \\
        --per-keyword 10
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
from tools.scraper.liepin_scraper import LiepinScraper


# 内置 30 个中高端中文关键词，覆盖猎聘核心目标人群（互联网/AI/金融/产品）。
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


def _normalize_liepin_url(raw: str) -> str:
    """规范化猎聘 URL：保留 /job/数字.shtml 部分，去 query/fragment。"""
    if not raw:
        return ""
    m = re.match(r"(https?://(?:www\.)?liepin\.com/job/\d+\.shtml)", raw)
    return m.group(1) if m else raw


def _map_to_jd_row(job: Dict[str, Any], keyword: str) -> Dict[str, Any]:
    """LiepinScraper.parse_job 返回的 dict → jds 表 schema。"""
    raw_text = job.get("raw_text") or job.get("description") or ""
    url = _normalize_liepin_url(job.get("url") or "")
    return {
        "url": url or f"liepin://unknown/{hash(raw_text)}",
        "title": job.get("title") or "",
        "company": job.get("company") or "",
        "location": job.get("location") or "全国",
        "salary_str": job.get("salary_range") or "",
        "raw_text": raw_text,
        "source": "liepin_batch",
        "search_keyword": keyword,
        "platform": "liepin",
        "language": "zh",
        "industry_tag": None,
        "function_tag": None,
        "position_tag": None,
        "auto_classified": 0,
        "is_public": 0,
    }


async def crawl_one_keyword(
    scraper: LiepinScraper,
    keyword: str,
    per_keyword: int,
    db,
) -> Dict[str, int]:
    stats = {"fetched": 0, "inserted": 0, "skipped": 0, "failed": 0}
    logger.info(f"[{keyword}] search start, target={per_keyword}")

    try:
        jobs = await scraper.search_jobs(keyword=keyword, limit=per_keyword * 2)
    except Exception as exc:
        logger.error(f"[{keyword}] search_jobs failed: {exc}")
        stats["failed"] = per_keyword
        return stats

    logger.info(f"[{keyword}] search returned {len(jobs)} job cards")

    for job in jobs[:per_keyword]:
        job_url = job.get("url")
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
            db.insert_jd(row)
            stats["inserted"] += 1
            stats["fetched"] += 1
        except Exception as exc:
            logger.warning(f"[{keyword}] insert_jd failed: {exc}")
            stats["skipped"] += 1

    logger.info(f"[{keyword}] done: {stats}")
    return stats


async def run(
    keywords: List[str],
    per_keyword: int,
    headless: bool,
    batch_size: int = 2,
) -> Dict[str, int]:
    """分批跑：每 batch_size 个关键词 close + 重启一次浏览器（N9 教训）。"""
    db = get_db()
    total = {"fetched": 0, "inserted": 0, "skipped": 0, "failed": 0}

    scraper: Optional[LiepinScraper] = None
    try:
        # 第一次启动前做登录态检查，但只 warn 不 block——
        # 猎聘改版后旧 selector 可能失效，真的没登录搜索页会重定向到登录页，到时再失败。
        scraper = LiepinScraper(headless=headless)
        login_ok = await scraper.check_login()
        if not login_ok:
            logger.warning(
                "[liepin] check_login selector 没匹配上用户节点，但 profile 已存在；"
                "继续尝试搜索，若被重定向到登录页再停。"
            )
        else:
            logger.info("[liepin] 登录态 OK，开始批量爬取")

        for i, kw in enumerate(keywords):
            if scraper is None:
                scraper = LiepinScraper(headless=headless)
                logger.info(f"[batch] new scraper started at keyword #{i+1}")

            stats = await crawl_one_keyword(scraper, kw, per_keyword, db)
            for k in total:
                total[k] += stats[k]

            if (i + 1) % batch_size == 0 and i < len(keywords) - 1:
                logger.info(f"[batch] restarting browser after {i+1} keywords")
                try:
                    await scraper.close()
                except Exception:
                    pass
                scraper = None
                await asyncio.sleep(2)
    finally:
        if scraper is not None:
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
        description="Batch crawl Liepin (中高端) and insert into jds table"
    )
    parser.add_argument("--keyword", help="单关键词（冒烟用）")
    parser.add_argument("--keywords-file", help="多关键词文件，每行一个")
    parser.add_argument("--default-keywords", action="store_true", help="用内置 30 个中文关键词")
    parser.add_argument("--per-keyword", type=int, default=10, help="每词抓多少条（默认 10）")
    parser.add_argument(
        "--batch-size", type=int, default=2,
        help="每多少关键词重启一次浏览器（默认 2）",
    )
    parser.add_argument("--no-headless", action="store_true", help="显示浏览器（调试用）")
    args = parser.parse_args()

    keywords = _load_keywords(args)
    logger.info(
        f"keywords={len(keywords)}个  per_keyword={args.per_keyword}  "
        f"batch_size={args.batch_size}  headless={not args.no_headless}"
    )

    total = asyncio.run(
        run(
            keywords,
            args.per_keyword,
            headless=not args.no_headless,
            batch_size=args.batch_size,
        )
    )

    print("\n=== Liepin Batch Crawl Result ===")
    print(f"  Keywords run:    {len(keywords)}")
    print(f"  Total fetched:   {total['fetched']}")
    print(f"  Inserted:        {total['inserted']}")
    print(f"  Skipped (dup):   {total['skipped']}")
    print(f"  Failed:          {total['failed']}")


if __name__ == "__main__":
    main()
