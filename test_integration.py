#!/usr/bin/env python3
"""
测试 JobHunter 集成
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

import asyncio
from loguru import logger

from tools.scraper.jobsdb_scraper import JobsDBScraper
from tools.scraper.job_database import JobDatabase


async def test_scraper():
    """测试爬虫基本功能"""
    print("=" * 60)
    print("测试 JobsDBScraper")
    print("=" * 60)

    try:
        async with JobsDBScraper(headless=False, human_speed=1.0) as scraper:
            # 测试搜索
            print("\n1. 测试搜索...")
            jobs = await scraper.search_jobs(keyword="AI Product Manager", page=1, posted_within=7)
            print(f"   找到 {len(jobs)} 个职位")

            if jobs:
                # 测试解析第一个职位
                print("\n2. 测试职位详情...")
                first_job = jobs[0]
                job_url = first_job.get("url")
                print(f"   解析: {job_url}")

                job_detail = await scraper.parse_job(job_url)
                print(f"   标题: {job_detail.get('title')}")
                print(f"   公司: {job_detail.get('company')}")
                print(f"   薪资: {job_detail.get('salary_str')}")

                # 测试数据库
                print("\n3. 测试数据库...")
                db = JobDatabase()
                job_detail["search_keyword"] = "AI Product Manager"
                db.insert(job_detail)
                print(f"   数据库当前总数: {db.get_count()}")

        print("\n✅ 测试通过!")
        return True

    except Exception as e:
        logger.exception(f"❌ 测试失败: {e}")
        return False


async def test_database():
    """测试数据库功能"""
    print("\n" + "=" * 60)
    print("测试 JobDatabase")
    print("=" * 60)

    db = JobDatabase()

    print(f"\n1. 数据库总数: {db.get_count()}")

    print("\n2. 获取最近的职位...")
    recent = db.get_recent(days=30, limit=10)
    for i, job in enumerate(recent[:3], 1):
        print(f"   {i}. {job.get('title')} @ {job.get('company')}")

    print("\n3. 统计信息:")
    stats = db.get_stats()
    print(f"   总数: {stats.get('total')}")
    print(f"   按平台: {stats.get('by_platform')}")

    print("\n✅ 数据库测试完成!")


def main():
    print("\nJobHunter 集成测试\n")

    # 测试数据库（不需要浏览器）
    asyncio.run(test_database())

    # 询问是否测试爬虫
    choice = input("\n是否测试爬虫 (需要浏览器)? (y/n): ").strip().lower()
    if choice == "y":
        asyncio.run(test_scraper())


if __name__ == "__main__":
    main()

