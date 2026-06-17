#!/usr/bin/env python3
"""
JobsDB 登录助手

使用方法：
1. 运行此脚本
2. 在打开的浏览器中手动登录 JobsDB
3. 登录成功后，在终端按回车
4. 关闭浏览器
5. 之后使用爬虫时会自动保持登录状态
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
    """登录助手"""
    print("="*60)
    print("Job Hunter - JobsDB 登录助手")
    print("="*60)
    print()
    print("步骤：")
    print("1. 浏览器会自动打开并访问 JobsDB")
    print("2. 请在浏览器中手动登录你的 JobsDB 账号")
    print("3. 登录成功后，回到这里按回车继续")
    print()

    # 使用持久化上下文
    from pathlib import Path
    user_data_dir = Path.home() / ".job_hunter" / "browser_data" / "jobsdb"

    scraper = JobsDBScraper(
        headless=False,
        user_data_dir=str(user_data_dir),
        browser_type="chromium"  # 先用 Chrome
    )

    try:
        await scraper.start()

        # 访问 JobsDB
        print("正在打开 JobsDB...")
        await scraper.navigate("https://hk.jobsdb.com")

        # 等待用户登录
        print()
        print("请在浏览器中登录 JobsDB...")
        print("登录完成后，在终端按回车继续...")
        input()

        # 验证是否登录
        print("正在验证登录状态...")
        await asyncio.sleep(2)

        # 截图保存
        try:
            screenshot_path = await scraper.take_screenshot("jobsdb_logged_in.png")
            print(f"已保存登录后截图: {screenshot_path}")
        except Exception as e:
            print(f"截图失败: {e}")

        print()
        print("✅ 登录状态已保存！")
        print(f"用户数据保存在: {user_data_dir}")
        print()
        print("之后使用爬虫时会自动保持登录状态。")
        print()

        # 测试一下搜索
        print("要测试一下搜索吗？(y/n): ", end="")
        choice = input().strip().lower()

        if choice == 'y':
            keyword = input("输入搜索关键词 (默认: AI): ").strip() or "AI"
            print(f"正在搜索 '{keyword}'...")

            jobs = await scraper.search_jobs(keyword=keyword, page=1)
            print(f"找到 {len(jobs)} 个职位:")
            for i, job in enumerate(jobs[:5], 1):
                print(f"  {i}. {job.get('title', 'N/A')} @ {job.get('company', 'N/A')}")

    except Exception as e:
        logger.exception(f"出错: {e}")
        return 1
    finally:
        try:
            await scraper.close()
        except:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
