#!/usr/bin/env python3
"""
智能 JD 收集器 - Microsoft Edge 版

你正常在浏览器中浏览 JobsDB，我们后台帮忙：
1. 自动监测你何时打开职位页面
2. 一键保存当前查看的职位
3. 批量处理和导入数据库

使用方法：
1. 运行此脚本
2. 在打开的浏览器中正常浏览 JobsDB
3. 看到感兴趣的职位，在终端按 S 保存
4. 输入 Q 退出
"""

import sys
from pathlib import Path
import os

# 添加项目根目录
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

import asyncio
import json
from datetime import datetime
from loguru import logger

from tools.scraper.human_playwright_scraper import HumanPlaywrightScraper


def get_smart_user_data_dir():
    """获取智能的用户数据目录 - 用我们自己的独立目录，但持久保存登录状态"""
    edge_dir = Path.home() / ".job_hunter" / "edge_profile"
    return str(edge_dir)


class SmartCollector(HumanPlaywrightScraper):
    """智能 JD 收集器"""

    def __init__(self):
        # 使用我们自己的持久化目录 - 你第一次登录后，后续会保持登录！
        user_data_dir = get_smart_user_data_dir()

        super().__init__(
            platform_name="jobsdb",
            headless=False,
            browser_type="msedge",
            user_data_dir=user_data_dir,
            human_speed=1.0,
        )

        self.saved_jobs = []
        self.save_dir = Path.home() / ".job_hunter" / "collected_jds"
        self.save_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Edge Profile: {user_data_dir}")
        logger.info("第一次登录后，后续会保持登录状态！")

    async def run_interactive(self):
        """运行交互式收集"""
        print("="*60)
        print("Job Hunter - 智能 JD 收集器 (Edge 版)")
        print("="*60)
        print("\n使用说明：")
        print("1. 浏览器已打开 JobsDB")
        print("2. 正常浏览，找到你感兴趣的职位")
        print("3. 在当前职位页面时，回到终端输入命令")
        print("\n命令：")
        print("  S  - 保存当前职位")
        print("  L  - 列出已保存职位")
        print("  Q  - 退出并保存全部")
        print("  ?  - 显示帮助")
        print()

        # 打开 JobsDB
        await self.human_navigate("https://hk.jobsdb.com")
        print("Edge 浏览器已打开！开始浏览吧！")

        while True:
            try:
                cmd = input("\n输入命令 > ").strip().upper()

                if cmd == "Q":
                    await self._quit_and_save()
                    break
                elif cmd == "S":
                    await self._save_current_job()
                elif cmd == "L":
                    await self._list_saved()
                elif cmd == "?" or cmd == "H":
                    await self._show_help()
                elif cmd == "":
                    continue
                else:
                    print(f"未知命令: {cmd}，输入 ? 查看帮助")

            except KeyboardInterrupt:
                print("\n检测到中断，保存后退出...")
                await self._quit_and_save()
                break
            except Exception as e:
                logger.exception(f"出错: {e}")

    async def _save_current_job(self):
        """保存当前页面的职位"""
        try:
            # 获取当前 URL
            current_url = self.page.url
            print(f"\n当前页面: {current_url[:60]}")

            if "jobsdb.com/job/" not in current_url.lower() and "-job-" not in current_url.lower():
                print("❌ 这看起来不是职位详情页，请先点击一个职位进入详情页")
                return

            # 获取页面内容
            page_text = await self.page.inner_text("body")
            page_title = await self.page.title()

            # 获取职位标题
            title = page_title
            try:
                h1_elements = await self.page.query_selector_all("h1, h2")
                for elem in h1_elements:
                    text = (await elem.inner_text()).strip()
                    if text and len(text) > 5:
                        title = text
                        break
            except Exception:
                pass

            # 保存
            job_data = {
                "title": title,
                "url": current_url,
                "raw_text": page_text,
                "saved_at": datetime.now().isoformat(),
                "source": "smart_collector"
            }

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = self.save_dir / f"job_{timestamp}.json"

            with open(filename, "w", encoding="utf-8") as f:
                json.dump(job_data, f, ensure_ascii=False, indent=2)

            self.saved_jobs.append(job_data)
            print(f"✅ 已保存职位！")
            print(f"   标题: {title[:50]}")
            print(f"   文件: {filename.name}")
            print(f"   已保存: {len(self.saved_jobs)} 个职位")

        except Exception as e:
            logger.exception(f"保存失败: {e}")

    async def _list_saved(self):
        """列出已保存职位"""
        if not self.saved_jobs:
            print("当前会话还没有保存任何职位")
            return

        print(f"\n已保存 {len(self.saved_jobs)} 个职位：")
        for idx, job in enumerate(self.saved_jobs):
            print(f"{idx+1}. {job.get('title', 'N/A')[:60]}")

    async def _show_help(self):
        """显示帮助"""
        print("\n帮助信息：")
        print("  S - 保存当前职位（需要在职位详情页）")
        print("  L - 列出已保存职位")
        print("  Q - 退出程序并完成保存")
        print("  ? - 显示此帮助")
        print("\n提示：")
        print("  - 保存前先在浏览器中点击职位进入详情页")
        print("  - 保存的数据在 ~/.job_hunter/collected_jds/")

    async def _quit_and_save(self):
        """退出并保存记录"""
        print("\n" + "="*60)
        print(f"收集完成！本次共保存 {len(self.saved_jobs)} 个职位")
        print(f"数据保存在: {self.save_dir}")
        print("="*60)


async def main():
    """主函数"""
    collector = SmartCollector()
    await collector.start()

    try:
        await collector.run_interactive()
    finally:
        await collector.close()


if __name__ == "__main__":
    asyncio.run(main())
