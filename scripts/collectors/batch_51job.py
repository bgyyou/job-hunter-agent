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

    # N10 中等放量：100 关键词 × 5 大城市 × 20 条 ≈ 10000 JD，分批冷却
    python scripts/collectors/batch_51job.py --default-keywords --per-keyword 20 \
        --cities "深圳,北京,上海,广州,杭州" \
        --rest-every 20 --rest-seconds 60
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


# 内置 100 个中端 + 长尾关键词（N10 扩容：30 核心 + 70 长尾）
DEFAULT_KEYWORDS = [
    # AI / 数据（6）
    "AI产品经理", "算法工程师", "机器学习工程师", "数据科学家",
    "大模型工程师", "NLP工程师",
    # 产品（5）
    "产品经理", "高级产品经理", "产品总监", "产品运营", "产品助理",
    # 技术核心（6）
    "Java工程师", "Python开发", "前端工程师", "全栈工程师",
    "架构师", "技术总监",
    # DevOps / 数据（4）
    "DevOps工程师", "数据分析师", "商业分析师", "数据工程师",
    # 运营 / 市场（4）
    "用户增长", "增长黑客", "运营经理", "市场总监",
    # 金融（3）
    "量化研究员", "投资经理", "风控经理",
    # 其他高薪（2）
    "HRBP", "供应链总监",
] + [
    # 技术长尾（14）
    "嵌入式工程师", "单片机工程师", "硬件工程师", "测试工程师",
    "自动化测试", "Python后端", "Go开发", "数据仓库",
    "ETL工程师", "BI工程师", "运维工程师", "SRE",
    "网络安全", "信息安全",
    # 设计 / 创意（8）
    "UI设计师", "UX设计师", "平面设计", "视觉设计",
    "插画师", "广告设计", "动画设计", "网页设计",
    # 运营长尾（10）
    "运营专员", "内容运营", "社群运营", "活动运营",
    "电商运营", "直播运营", "新媒体运营", "短视频运营",
    "淘宝运营", "天猫运营",
    # 销售 / 客户（9）
    "销售经理", "销售助理", "客户经理", "渠道经理",
    "大客户销售", "海外销售", "外贸业务员", "电话销售", "商务代表",
    # HR / 行政 / 法务（7）
    "招聘专员", "培训专员", "HRBP专员", "行政专员",
    "前台", "文秘", "法务专员",
    # 财务 / 采购 / 供应链（6）
    "会计", "出纳", "审计", "税务", "采购", "供应链",
    # 市场长尾（5）
    "市场专员", "品牌专员", "公关", "媒介", "广告策划",
    # 教育 / 医疗（5）
    "课程顾问", "培训师", "医药代表", "临床监察员", "CRC",
    # 海外 / 跨境（6）
    "跨境电商运营", "亚马逊运营", "Shopee运营", "海外市场", "海外运营", "海外技术支持",
]

DEFAULT_CITIES = ["深圳", "北京", "上海", "广州", "杭州"]


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
    cities: Optional[List[str]],
    request_interval_min: float = 3.0,
    request_interval_max: float = 6.0,
    rest_every: int = 0,
    rest_seconds: float = 0.0,
) -> Dict[str, int]:
    """笛卡尔积跑批：每个 (keyword, city) 组合都跑一次。

    Args:
        cities: 城市列表；None 或 [] 表示默认全国
        rest_every: 每 N 个组合后休息 rest_seconds 秒（0 = 不休息）
        rest_seconds: 每次休息秒数
    """
    db = get_db()
    total = {"fetched": 0, "inserted": 0, "skipped": 0, "failed": 0}

    scraper = FiftyOneJobScraper(
        request_interval_min=request_interval_min,
        request_interval_max=request_interval_max,
    )

    city_list = cities or [None]  # None 表示全国
    combos = [(kw, c) for c in city_list for kw in keywords]
    total_combos = len(combos)
    logger.info(
        f"[batch] 笛卡尔积: {len(keywords)} keywords × {len(city_list)} cities = {total_combos} 组合"
    )

    try:
        for i, (kw, city) in enumerate(combos):
            stats = await crawl_one_keyword(scraper, kw, per_keyword, city, db)
            for k in total:
                total[k] += stats[k]

            logger.info(
                f"[batch] progress {i+1}/{total_combos} (kw={kw}, city={city or '全国'}): total={total}"
            )

            # 每 N 组合后强制冷却，避免触发 30 分钟风控
            if rest_every > 0 and rest_seconds > 0 and (i + 1) % rest_every == 0 and (i + 1) < total_combos:
                logger.info(
                    f"[batch] 已跑 {i+1}/{total_combos} 组合，冷却 {rest_seconds}s 后继续…"
                )
                await asyncio.sleep(rest_seconds)

            # 组合之间小幅间隔
            if i < total_combos - 1:
                await asyncio.sleep(2)
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
    parser.add_argument("--default-keywords", action="store_true", help="用内置 100 个中文关键词")
    parser.add_argument("--per-keyword", type=int, default=20, help="每词抓多少条（默认 20）")
    parser.add_argument("--city", help="单城市，如 上海 / 深圳（默认全国），与 --cities 互斥")
    parser.add_argument(
        "--cities", help="多城市，逗号分隔，如 '深圳,北京,上海,广州,杭州'，与 --city 互斥"
    )
    parser.add_argument(
        "--interval-min", type=float, default=3.0,
        help="请求间隔最小秒数（默认 3.0）",
    )
    parser.add_argument(
        "--interval-max", type=float, default=6.0,
        help="请求间隔最大秒数（默认 6.0）",
    )
    parser.add_argument(
        "--rest-every", type=int, default=0,
        help="每 N 个 (kw,city) 组合后冷却一次（默认 0 = 不冷却）",
    )
    parser.add_argument(
        "--rest-seconds", type=float, default=60.0,
        help="冷却秒数（默认 60.0）",
    )
    args = parser.parse_args()

    keywords = _load_keywords(args)
    if args.city and args.cities:
        logger.error("--city 和 --cities 互斥，请只用一个")
        sys.exit(2)
    if args.cities:
        cities = [c.strip() for c in args.cities.split(",") if c.strip()]
    elif args.city:
        cities = [args.city]
    else:
        cities = [None]  # 默认全国

    logger.info(
        f"keywords={len(keywords)}个  per_keyword={args.per_keyword}  "
        f"cities={cities}  interval=[{args.interval_min},{args.interval_max}]s  "
        f"rest_every={args.rest_every}  rest_seconds={args.rest_seconds}"
    )

    total = asyncio.run(
        run(
            keywords,
            args.per_keyword,
            cities=cities,
            request_interval_min=args.interval_min,
            request_interval_max=args.interval_max,
            rest_every=args.rest_every,
            rest_seconds=args.rest_seconds,
        )
    )

    print("\n=== 51job Batch Crawl Result ===")
    print(f"  Combos run:     {len(keywords) * len(cities)}")
    print(f"  Keywords:       {len(keywords)}")
    print(f"  Cities:         {cities}")
    print(f"  Total fetched:  {total['fetched']}")
    print(f"  Inserted:       {total['inserted']}")
    print(f"  Skipped (dup):  {total['skipped']}")
    print(f"  Failed:         {total['failed']}")


if __name__ == "__main__":
    main()
