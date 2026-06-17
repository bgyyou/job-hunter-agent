# -*- coding: utf-8 -*-
"""Entry script for the JobHunter crawler module.

Usage:
    # Crawl Boss直聘 for "AI产品经理"
    python crawler/run_crawler.py --site boss --keyword "AI产品经理" --limit 20

    # Crawl Lagou
    python crawler/run_crawler.py --site lagou --keyword "AI产品经理" --limit 20

    # Crawl Indeed China
    python crawler/run_crawler.py --site indeed --keyword "AI产品经理" --limit 20

    # Add cookies file (Boss直聘 requires login cookies)
    python crawler/run_crawler.py --site boss --keyword "Python" --limit 10 \
        --cookies data/cookies/boss.json

Supported sites:
    boss      Boss直聘 (requires cookies)
    lagou     拉勾网 (requires cookies)
    indeed    Indeed 中国
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from crawler.base_crawler import BaseCrawler, CrawlerSettings
from crawler.pipeline import CrawlPipeline


SUPPORTED_SITES = {
    "boss": ("crawler.sites.boss.BossCrawler", "Boss直聘 (zhipin.com)"),
    "lagou": ("crawler.sites.lagou.LagouCrawler", "拉勾网 (lagou.com)"),
    "indeed": ("crawler.sites.indeed.IndeedCrawler", "Indeed 中国 (cn.indeed.com)"),
    "liepin": ("", "猎聘 (liepin.com) — not yet implemented"),
    "jobsdb": ("", "JobsDB HK (jobsdb.com) — not yet implemented"),
}


def _load_cookies(cookies_file: str) -> Optional[List[Dict[str, Any]]]:
    """Load cookies from a JSON file.

    Expected format (Netscape-style or JSON array):
        [{"name": "device_id", "value": "..."}, ...]
    """
    path = Path(cookies_file)
    if not path.exists():
        logger.warning(f"[Cookies] File not found: {cookies_file}")
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            logger.info(f"[Cookies] Loaded {len(data)} cookies from {cookies_file}")
            return data
        logger.warning("[Cookies] Expected JSON array, got object")
        return None
    except Exception as exc:
        logger.error(f"[Cookies] Failed to load: {exc}")
        return None


SITES_SUPPORTING_BROWSER = {"boss"}


def _resolve_crawler_class(site: str):
    """Import and return the crawler class for the given site name."""
    module_path, desc = SUPPORTED_SITES.get(site, ("", "unknown"))
    if not module_path:
        raise ValueError(f"Site '{site}' is not yet implemented: {desc}")
    mod_name, cls_name = module_path.rsplit(".", 1)
    mod = __import__(mod_name, fromlist=[cls_name])
    return getattr(mod, cls_name)


def _create_crawler(site: str, crawler_cls, cookies, use_browser: bool):
    """Instantiate a crawler, passing use_browser only for supported sites."""
    if site in SITES_SUPPORTING_BROWSER:
        return crawler_cls(cookies=cookies, use_browser=use_browser)
    return crawler_cls(cookies=cookies)


def _run_interactive() -> None:
    """Interactive mode: prompt user for crawl parameters."""
    print("\n=== JobHunter Crawler — Interactive Mode ===\n")
    print("Supported sites:")
    for name, (_, desc) in SUPPORTED_SITES.items():
        print(f"  {name:10s} — {desc}")
    print()

    site = input("Site (boss/lagou/indeed/liepin/jobsdb) [boss]: ").strip() or "boss"
    if site not in SUPPORTED_SITES:
        logger.error(f"Unknown site: {site}")
        return

    keyword = input("Search keyword [AI产品经理]: ").strip() or "AI产品经理"
    limit_str = input("Limit [20]: ").strip()
    limit = int(limit_str) if limit_str.isdigit() else 20

    cookies_file = input("Cookies file (empty to skip) []: ").strip()
    cookies = _load_cookies(cookies_file) if cookies_file else None

    use_browser = input("Use browser mode (Edge reuse)? [no]: ").strip().lower() in ("y", "yes", "1")

    city = input("City code (empty for default) []: ").strip()
    if not city:
        city = "101010100"  # Beijing default

    print(f"\nStarting: site={site}, keyword='{keyword}', limit={limit}, browser={use_browser}\n")

    try:
        crawler_cls = _resolve_crawler_class(site)
        crawler = _create_crawler(site, crawler_cls, cookies, use_browser)
        pipeline = CrawlPipeline(crawler=crawler)
        result = pipeline.run(keyword=keyword, limit=limit, city=city)
        print(f"\nResult: {result}")
    except Exception as exc:
        logger.error(f"Crawl failed: {exc}")
        raise


def _run_direct(args: argparse.Namespace) -> None:
    """Non-interactive mode: run with CLI arguments."""
    site = args.site
    keyword = args.keyword
    limit = args.limit
    city = args.city
    cookies_file = args.cookies
    use_browser = args.use_browser

    # Validate site
    if site not in SUPPORTED_SITES:
        logger.error(f"Unsupported site: {site}. Supported: {list(SUPPORTED_SITES.keys())}")
        sys.exit(1)

    # Load cookies if provided
    cookies = _load_cookies(cookies_file) if cookies_file else None

    # Resolve crawler class
    try:
        crawler_cls = _resolve_crawler_class(site)
    except ValueError as exc:
        logger.error(str(exc))
        sys.exit(1)

    # Create crawler and pipeline
    crawler = _create_crawler(site, crawler_cls, cookies, use_browser)
    pipeline = CrawlPipeline(crawler=crawler)

    # Run
    result = pipeline.run(keyword=keyword, limit=limit, city=city)
    print(f"\n=== Crawl Result ===")
    print(f"  Total fetched: {result['total_fetched']}")
    print(f"  Inserted:      {result['inserted']}")
    print(f"  Skipped (dup): {result['skipped']}")


def main():
    parser = argparse.ArgumentParser(
        description="JobHunter Crawler — crawl job listings and insert into DB",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Crawl Boss直聘 for "AI产品经理"
  python crawler/run_crawler.py --site boss --keyword "AI产品经理" --limit 20

  # With cookies
  python crawler/run_crawler.py --site boss --keyword "Python" --limit 10 \\
      --cookies data/cookies/boss.json

  # Use Edge browser to reuse login session (no cookies needed)
  python crawler/run_crawler.py --site boss --keyword "AI产品经理" --limit 1 \\
      --use-browser

  # Interactive mode
  python crawler/run_crawler.py --interactive
        """,
    )
    parser.add_argument(
        "--site",
        choices=list(SUPPORTED_SITES.keys()),
        default="boss",
        help="Crawl target site (default: boss)",
    )
    parser.add_argument(
        "--keyword",
        default="AI产品经理",
        help="Search keyword (default: AI产品经理)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Max JDs to fetch (default: 20)",
    )
    parser.add_argument(
        "--city",
        default="101010100",
        help="City code for Boss直聘 (default: 101010100 = Beijing)",
    )
    parser.add_argument(
        "--cookies",
        default=None,
        help="Path to cookies JSON file (default: none)",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Run in interactive prompt mode",
    )
    parser.add_argument(
        "--use-browser",
        action="store_true",
        help="Use Playwright to reuse local Edge login session "
             "(overrides --cookies, requires Edge to be logged in)",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Log level (default: INFO)",
    )

    args = parser.parse_args()

    # Configure loguru
    logger.remove()
    logger.add(sys.stderr, level=args.log_level, colorize=True, format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>")

    if args.interactive:
        _run_interactive()
    else:
        _run_direct(args)


if __name__ == "__main__":
    main()
