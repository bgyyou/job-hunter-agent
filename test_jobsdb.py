#!/usr/bin/env python3
"""
测试 JobsDB 爬虫
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

import asyncio
from loguru import logger

from tools.scraper.jobsdb_scraper import JobsDBScraper


async def main():
    """测试 JobsDB 爬虫"""
    logger.info("开始测试 JobsDB 爬虫")

    try:
        async with JobsDBScraper(headless=False) as scraper:
            # 搜索职位
            logger.info("搜索 'AI' 相关职位...")
            jobs = await scraper.search_jobs(
                keyword="AI",
                location=None,
                page=1
            )

            logger.info(f"\n找到 {len(jobs)} 个职位:\n")

            for i, job in enumerate(jobs[:10], 1):
                print(f"{i}. {job.get('title', 'N/A')}")
                print(f"   公司: {job.get('company', 'N/A')}")
                print(f"   地点: {job.get('location', 'N/A')}")
                print(f"   薪资: {job.get('salary', 'N/A')}")
                print(f"   URL: {job.get('url', 'N/A')}")
                print()

            if not jobs:
                logger.warning("未找到任何职位，请查看截图了解页面情况")

    except Exception as e:
        logger.exception(f"测试失败: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
