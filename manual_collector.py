#!/usr/bin/env python3
"""
手动 JD 收集器

使用方法：
1. 运行此脚本
2. 在打开的浏览器中正常浏览 JobsDB
3. 每找到一个感兴趣的职位，就回到终端按回车
4. 脚本会自动保存当前页面的职位信息
5. 完成后输入 'q' 退出
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

import asyncio
import json
from datetime import datetime
from loguru import logger

from tools.scraper.jobsdb_scraper import JobsDBScraper


async def main():
    """JD 收集器"""
    print("="*60)
    print("Job Hunter - JD 手动收集器")
    print("="*60)
    print()
    print("使用说明：")
    print("1. 浏览器会自动打开")
    print("2. 你可以正常浏览 JobsDB，搜索感兴趣的职位")
    print("3. 找到一个职位页面后，回到终端按回车")
    print("4. 脚本会自动保存当前职位")
    print("5. 继续找下一个，或输入 'q' 退出")
    print()

    # 使用持久化上下文
    from pathlib import Path
    user_data_dir = Path.home() / ".job_hunter" / "browser_data" / "jobsdb"

    scraper = JobsDBScraper(
        headless=False,
        user_data_dir=str(user_data_dir),
        browser_type="chromium"
    )

    # 保存目录
    output_dir = Path.home() / ".job_hunter" / "collected_jds"
    output_dir.mkdir(parents=True, exist_ok=True)

    collected_count = 0

    try:
        await scraper.start()

        # 先打开 JobsDB
        print("正在打开 JobsDB...")
        await scraper.navigate("https://hk.jobsdb.com")

        print()
        print("浏览器已打开！")
        print("开始浏览吧，找到好职位就回来按回车保存～")
        print()

        while True:
            print("-" * 60)
            print(f"已收集: {collected_count} 个职位")
            print()
            cmd = input("按回车保存当前页面，或输入 'q' 退出: ").strip().lower()

            if cmd == 'q':
                break

            try:
                # 获取当前页面信息
                print("正在保存...")

                # 获取页面内容
                page_url = scraper.page.url
                page_title = await scraper.page.title()
                page_html = await scraper.page.content()

                # 尝试提取职位信息
                try:
                    title_elem = await scraper.page.query_selector("h1")
                    title = await title_elem.inner_text() if title_elem else page_title
                except:
                    title = page_title

                # 获取页面全部文本
                page_text = await scraper.page.inner_text("body")

                # 保存
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_file = output_dir / f"jd_{timestamp}.json"

                jd_data = {
                    "title": title,
                    "url": page_url,
                    "raw_text": page_text,
                    "raw_html": page_html,
                    "collected_at": datetime.now().isoformat(),
                    "source": "jobsdb"
                }

                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(jd_data, f, ensure_ascii=False, indent=2)

                collected_count += 1
                print(f"✅ 已保存! ({output_file.name})")
                print(f"   职位: {title[:50]}...")

            except Exception as e:
                logger.exception(f"保存失败: {e}")
                print(f"❌ 保存失败: {e}")

        print()
        print("="*60)
        print(f"收集完成！共收集 {collected_count} 个职位")
        print(f"保存在: {output_dir}")
        print("="*60)
        print()
        print("要导入这些 JD 到知识库吗？(y/n): ", end="")

        choice = input().strip().lower()
        if choice == 'y':
            await import_to_knowledge_base(output_dir)

    except Exception as e:
        logger.exception(f"出错: {e}")
        return 1
    finally:
        try:
            await scraper.close()
        except:
            pass

    return 0


async def import_to_knowledge_base(jd_dir: Path):
    """导入 JD 到知识库"""
    print()
    print("正在导入到知识库...")

    try:
        from tools.knowledge_base import KnowledgeBase
        from tools.llm import VolcanoClient
        import os
        from dotenv import load_dotenv

        load_dotenv()

        # 初始化 LLM 客户端
        llm_client = VolcanoClient(
            api_key=os.getenv("VOLCANO_API_KEY", ""),
            api_url=os.getenv("VOLCANO_CODING_API_URL", "https://apihub.agnes-ai.com/v1"),
            model=os.getenv("VOLCANO_MODEL", "agnes-2.0-flash"),
            is_coding_api=True,
            use_anthropic_format=os.getenv("VOLCANO_USE_ANTHROPIC_FORMAT", "false").lower() == "true"
        )

        kb = KnowledgeBase()
        kb.set_llm_client(llm_client)

        jd_files = list(jd_dir.glob("jd_*.json"))
        imported_count = 0

        for jd_file in jd_files:
            try:
                with open(jd_file, 'r', encoding='utf-8') as f:
                    jd_data = json.load(f)

                # 分析并分类
                print(f"分析: {jd_data.get('title', 'Untitled')[:40]}...")
                classification = await kb.classify_jd({
                    "title": jd_data.get("title", ""),
                    "description": jd_data.get("raw_text", "")
                })

                # 保存
                kb.switch_database(classification["category"])
                jd_id = kb.add_jd({
                    "raw_text": jd_data.get("raw_text", ""),
                    "parsed_data": {
                        "title": jd_data.get("title", "")
                    },
                    "source": "manual_collector",
                    "url": jd_data.get("url", "")
                })

                print(f"  → 分类: {classification['category']} ({int(classification['confidence']*100)}%)")
                imported_count += 1

            except Exception as e:
                print(f"  ❌ 失败: {e}")

        print()
        print(f"✅ 导入完成！成功导入 {imported_count}/{len(jd_files)} 个 JD")

    except Exception as e:
        logger.exception(f"导入失败: {e}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
