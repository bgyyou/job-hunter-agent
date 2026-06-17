"""
测试 Edge 浏览器和登录持久化
"""
import asyncio
import sys
from pathlib import Path

# 修复 Windows 控制台编码
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from crawler import BaseScraper


async def test_edge_login():
    """测试 Edge 能否正常打开 JobsDB 并保持登录"""
    print("=" * 60)
    print("JobHunter - Edge Browser Test")
    print("=" * 60)

    scraper = BaseScraper(headless=False, human_speed=1.0)
    await scraper.start()

    try:
        # 打开 JobsDB
        print("\nOpening JobsDB...")
        await scraper.human_navigate("https://hk.jobsdb.com")

        print("\n[OK] Browser opened!")
        print("\nPlease check:")
        print("  1. Are you already logged into JobsDB?")
        print("  2. Is the page displaying correctly?")
        print("\nPress Ctrl+C to exit...")

        try:
            # 保持浏览器打开
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\n\nExiting...")

    finally:
        await scraper.close()


if __name__ == "__main__":
    asyncio.run(test_edge_login())
