#!/usr/bin/env python3
"""
导入收集的 JD 到知识库

使用方法：
1. 先用 smart_collector.py 收集一些 JD
2. 运行此脚本导入到知识库
"""

import sys
from pathlib import Path

# 添加项目根目录
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

import asyncio
import json
from loguru import logger

from tools.knowledge_base import KnowledgeBase
from tools.llm import VolcanoClient
from dotenv import load_dotenv
import os


async def import_collected_jobs():
    """导入收集的 JD 到知识库"""
    print("="*60)
    print("Job Hunter - 导入收集的 JD")
    print("="*60)

    # 加载环境变量
    load_dotenv()

    # 检查数据目录
    collected_dir = Path.home() / ".job_hunter" / "collected_jds"

    if not collected_dir.exists():
        print(f"\n❌ 数据目录不存在: {collected_dir}")
        print("请先用 smart_collector.py 收集一些职位")
        return

    # 找到所有 JD 文件
    job_files = list(collected_dir.glob("job_*.json"))
    job_files.sort()

    if not job_files:
        print(f"\n❌ 目录中没有找到收集的 JD")
        print("请先用 smart_collector.py 收集一些职位")
        return

    print(f"\n找到 {len(job_files)} 个收集的职位\n")

    # 初始化 LLM 和知识库
    api_key = os.getenv("VOLCANO_API_KEY", "")
    api_url = os.getenv("VOLCANO_CODING_API_URL", "https://apihub.agnes-ai.com/v1")
    model = os.getenv("VOLCANO_MODEL", "agnes-2.0-flash")

    if not api_key:
        print("⚠️  没有找到 VOLCANO_API_KEY，请设置后再运行")
        print("可以在 .env 文件中设置，或者设置环境变量")

    print("初始化知识库...")
    kb = KnowledgeBase()

    if api_key:
        llm = VolcanoClient(
            api_key=api_key,
            api_url=api_url,
            model=model,
            is_coding_api=True,
            use_anthropic_format=os.getenv("VOLCANO_USE_ANTHROPIC_FORMAT", "false").lower() == "true",
        )
        kb.set_llm_client(llm)
        print("✅ LLM 已初始化，将自动分类职位")
    else:
        print("⚠️  无 LLM API Key，跳过智能分类")

    # 导入每个 JD
    imported_count = 0
    for idx, job_file in enumerate(job_files, 1):
        try:
            print(f"\n处理 {idx}/{len(job_files)}: {job_file.name}")

            with open(job_file, "r", encoding="utf-8") as f:
                job_data = json.load(f)

            title = job_data.get("title", "Unknown")
            raw_text = job_data.get("raw_text", "")

            print(f"  标题: {title[:60]}")

            # 尝试分类
            category = "General"
            if api_key and hasattr(kb, "classify_jd"):
                try:
                    classification = await kb.classify_jd({
                        "title": title,
                        "description": raw_text
                    })
                    category = classification.get("category", "General")
                    print(f"  分类: {category}")
                except Exception as e:
                    logger.debug(f"分类失败: {e}")

            # 保存到知识库
            kb.switch_database(category)
            jd_id = kb.add_jd({
                "title": title,
                "raw_text": raw_text,
                "url": job_data.get("url", ""),
                "source": "smart_collector",
                "saved_at": job_data.get("saved_at", ""),
            })

            print(f"  ✅ 已保存到知识库 (ID: {jd_id})")
            imported_count += 1

            # 移动文件到已导入目录
            imported_dir = collected_dir / "imported"
            imported_dir.mkdir(exist_ok=True)
            target = imported_dir / job_file.name
            job_file.rename(target)

        except Exception as e:
            logger.exception(f"导入失败: {e}")
            print(f"  ❌ 失败: {e}")

    print("\n" + "="*60)
    print(f"导入完成！成功 {imported_count}/{len(job_files)}")
    print("="*60)

    # 显示统计
    stats = kb.get_statistics()
    print("\n知识库统计：")
    print(f"  总数据库: {stats.get('total_dbs', 0)}")
    print(f"  总职位数: {stats.get('total_jds', 0)}")


if __name__ == "__main__":
    asyncio.run(import_collected_jobs())
