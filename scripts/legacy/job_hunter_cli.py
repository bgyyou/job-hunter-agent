#!/usr/bin/env python3
"""
JobHunter CLI - JobHunter 命令行入口

功能：
- 一键爬取 JobsDB 职位
- 使用 JobSearcher Agent
- 保存到数据库
"""
import sys
import asyncio
import argparse
from pathlib import Path
from typing import List, Dict

# 添加项目路径
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from loguru import logger

from tools.scraper.jobsdb_scraper import JobsDBScraper
from tools.scraper.job_database import JobDatabase


async def crawl_jobsdb_direct(
    keywords: List[str],
    time_range,
    max_jobs: int = 50,
    human_speed: float = 0.5,
    headless: bool = False,
) -> Dict:
    """
    直接使用 JobsDBScraper 爬取职位

    Args:
        keywords: 关键词列表
        time_range: 时间范围（天数或 "any"）
        max_jobs: 最大爬取数量
        human_speed: 人类速度倍数
        headless: 是否无头模式

    Returns:
        爬取结果字典
    """
    print("=" * 60)
    print("JobHunter - JobsDB 直接爬取模式")
    print("=" * 60)

    # 初始化数据库
    db = JobDatabase()
    initial_count = db.get_count()

    time_label = "任意时间" if time_range == "any" else f"{time_range}天"
    print(f"\n关键词: {', '.join(keywords)}")
    print(f"时间范围: {time_label}")
    print(f"最大数量: {max_jobs}")
    print(f"人类速度: {human_speed}x")
    print(f"数据库: {initial_count} 个职位已存在")
    print("\n开始爬取... (按 Ctrl+C 停止)\n")

    crawled_count = 0
    skipped_count = 0

    try:
        async with JobsDBScraper(headless=headless, human_speed=human_speed) as scraper:
            for keyword in keywords:
                if crawled_count >= max_jobs:
                    break

                logger.info(f"搜索关键词: {keyword}")

                for page in range(1, 11):  # 最多 10 页
                    if crawled_count >= max_jobs:
                        break

                    logger.info(f"搜索第 {page} 页: '{keyword}'")

                    # 处理时间参数
                    posted_within = None if time_range == "any" else int(time_range)

                    jobs = await scraper.search_jobs(
                        keyword=keyword,
                        page=page,
                        posted_within=posted_within
                    )

                    logger.info(f"第 {page} 页找到 {len(jobs)} 个职位")

                    for job in jobs:
                        if crawled_count >= max_jobs:
                            break

                        job_url = job.get("url", "")
                        if not job_url:
                            continue

                        # 检查是否已存在
                        if db.exists(job_url):
                            skipped_count += 1
                            logger.debug(f"跳过重复: {job_url}")
                            continue

                        try:
                            job_detail = await scraper.parse_job(job_url)
                            job_detail["search_keyword"] = keyword

                            db.insert(job_detail)
                            crawled_count += 1

                            title = job_detail.get("title", "")
                            days_old = job_detail.get("days_old", "?")
                            logger.info(f"[{crawled_count}/{max_jobs}] {title} ({days_old}天)")

                        except Exception as e:
                            logger.error(f"爬取失败 {job_url}: {e}")

        # 显示统计
        final_count = db.get_count()
        print(f"\n{'=' * 60}")
        print("完成!")
        print(f"  新增: {crawled_count}")
        print(f"  跳过重复: {skipped_count}")
        print(f"  数据库总数: {final_count}")
        print(f"{'=' * 60}")

        return {
            "crawled_count": crawled_count,
            "skipped_count": skipped_count,
            "final_count": final_count,
        }

    except KeyboardInterrupt:
        print(f"\n\n用户停止爬取")
        print(f"数据库总数: {db.get_count()}")
        return {}

    except Exception as e:
        logger.exception(f"爬虫失败: {e}")
        return {}


def show_database():
    """显示数据库内容"""
    db = JobDatabase()
    jobs = db.get_all(limit=50)

    print(f"\n数据库总职位数: {db.get_count()}")
    print("=" * 80)

    for i, job in enumerate(jobs, 1):
        print(f"{i}. {job.get('title', 'N/A')}")
        print(f"   公司: {job.get('company', 'N/A')}")
        print(f"   平台: {job.get('platform', 'N/A')}")
        print(f"   URL: {job.get('url', 'N/A')}")
        print(f"   关键词: {job.get('search_keyword', 'N/A')}")
        print(f"   发布天数: {job.get('days_old', 'N/A')}")
        print("-" * 80)

    # 显示统计
    stats = db.get_stats()
    print(f"\n统计:")
    print(f"  总数: {stats.get('total', 0)}")
    print(f"  按平台: {stats.get('by_platform', {})}")
    salary = stats.get('salary', {})
    if salary.get('count', 0) > 0:
        print(f"  平均薪资: {salary.get('avg_min', 0):.1f}K - {salary.get('avg_max', 0):.1f}K")


def interactive_mode():
    """交互式输入模式"""
    print("\n" + "=" * 60)
    print("⚙️  交互式设置")
    print("=" * 60)

    # 关键词
    while True:
        print("\n请输入关键词（多个关键词用逗号分隔）:")
        input_str = input("> ").strip()
        if input_str:
            keywords = [k.strip() for k in input_str.split(",") if k.strip()]
            if keywords:
                break
        print("❌ 关键词不能为空，请重新输入！")

    # 时间范围
    valid_time_options = {"3", "7", "14", "30", "0"}
    while True:
        print("\n请选择时间范围:")
        print("  [3] 最近3天")
        print("  [7] 最近7天")
        print("  [14] 最近14天")
        print("  [30] 最近30天")
        print("  [0] 任意时间")
        choice = input("请选择: ").strip()
        if choice in valid_time_options:
            if choice == "0":
                time_range = "any"
            else:
                time_range = int(choice)
            break
        print(f"❌ 无效选择，请输入 3, 7, 14, 30 或 0！")

    # 最大数量
    while True:
        print("\n请输入最大爬取数量:")
        input_str = input("> ").strip()
        if input_str.isdigit() and int(input_str) > 0:
            max_jobs = int(input_str)
            break
        print("❌ 请输入有效的正整数！")

    # 速度
    while True:
        print("\n请输入人类速度倍数（推荐0.3-2.0，默认0.5，按回车使用默认）:")
        input_str = input("> ").strip()
        if not input_str:
            human_speed = 0.5
            break
        try:
            human_speed = float(input_str)
            if 0.1 <= human_speed <= 5.0:
                break
            print("⚠️  警告：建议范围是0.3-2.0，但仍将使用该值")
            break
        except ValueError:
            print("❌ 请输入有效的数字！")

    # 无头模式
    while True:
        print("\n是否使用无头模式（不显示浏览器）? (y/n，默认n):")
        input_str = input("> ").strip().lower()
        if not input_str or input_str == "n":
            headless = False
            break
        if input_str == "y":
            headless = True
            break
        print("❌ 请输入 y 或 n！")

    # 确认
    time_label = "任意时间" if time_range == "any" else f"{time_range}天"
    print("\n" + "=" * 60)
    print("📋 确认设置:")
    print(f"  关键词: {', '.join(keywords)}")
    print(f"  时间范围: {time_label}")
    print(f"  最大数量: {max_jobs}")
    print(f"  人类速度: {human_speed}x")
    print(f"  无头模式: {'是' if headless else '否'}")
    print("=" * 60)

    confirm = input("\n确认开始爬取? (y/n): ").strip().lower()
    if confirm != "y":
        print("取消爬取。")
        return None

    return {
        "keywords": keywords,
        "time_range": time_range,
        "max_jobs": max_jobs,
        "human_speed": human_speed,
        "headless": headless
    }


def main():
    parser = argparse.ArgumentParser(
        description="JobHunter CLI - 职位搜索爬虫",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 交互式模式（推荐）
  python job_hunter_cli.py -i
  python job_hunter_cli.py --interactive

  # 命令行模式
  python job_hunter_cli.py --keywords "AI Product Manager" --time 7 --max 30

  # 查看数据库
  python job_hunter_cli.py --show
        """
    )

    parser.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="交互式输入模式（推荐）"
    )

    parser.add_argument(
        "--keywords",
        type=str,
        nargs="+",
        help="搜索关键词列表"
    )

    parser.add_argument(
        "--time",
        type=int,
        help="发布时间范围（天数，支持3/7/14/30）"
    )

    parser.add_argument(
        "--max",
        type=int,
        help="最大爬取数量"
    )

    parser.add_argument(
        "--speed",
        type=float,
        help="人类速度倍数（越小越慢）"
    )

    parser.add_argument(
        "--headless",
        action="store_true",
        help="无头模式（不显示浏览器）"
    )

    parser.add_argument(
        "--show",
        action="store_true",
        help="仅显示数据库内容"
    )

    args = parser.parse_args()

    if args.show:
        show_database()
        return

    if args.interactive:
        settings = interactive_mode()
        if settings:
            asyncio.run(crawl_jobsdb_direct(
                keywords=settings["keywords"],
                time_range=settings["time_range"],
                max_jobs=settings["max_jobs"],
                human_speed=settings["human_speed"],
                headless=settings["headless"]
            ))
        return

    # 命令行模式 - 检查必需参数
    if not args.keywords:
        print("❌ 请指定关键词，或使用 --interactive 进入交互式模式")
        print("运行示例: python job_hunter_cli.py -i")
        return

    if args.time is None:
        print("❌ 请指定时间范围，或使用 --interactive 进入交互式模式")
        print("运行示例: python job_hunter_cli.py -i")
        return

    if args.max is None:
        print("❌ 请指定最大数量，或使用 --interactive 进入交互式模式")
        print("运行示例: python job_hunter_cli.py -i")
        return

    asyncio.run(crawl_jobsdb_direct(
        keywords=args.keywords,
        time_range=args.time,
        max_jobs=args.max,
        human_speed=args.speed or 0.5,
        headless=args.headless
    ))


if __name__ == "__main__":
    main()
