#!/usr/bin/env python3
"""导入 collector 收集的 JD 到 v2 统一库（data/jobhunter_v2.db）

使用方法：
1. 先用 smart_collector.py 收集一些 JD
2. 运行此脚本导入：
       python scripts/collectors/import_collected.py --user-id <你的 user_id>

M-v4-2 (P1-002)：原实现走 v1 KnowledgeBase（多 DB 文件），与 v2 的
jobhunter_v2.db 不互通，导入后 Flow B 的 list_visible_jds 看不到。现改走
insert_user_jd + embed_and_store_jd_chunks，与 crawler/pipeline.py 同一条落库路径。

user_id 走必填 CLI 参数而非 web_app.current_user_id()：本脚本是纯 CLI 入口，
没有 Streamlit session，与 scripts/migrate_sqlite_to_pg.py 的 --user-id 一致。
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
from loguru import logger

load_dotenv(PROJECT_ROOT / ".env")

from database.classifier import Classifier
from database.factory import get_db
from services.jd_library_service import insert_user_jd
from tools.jd_indexer import embed_and_store_jd_chunks


def import_collected_jobs(user_id: str) -> int:
    """把 ~/.job_hunter/collected_jds/job_*.json 导入 v2 库。返回成功条数。"""
    print("=" * 60)
    print("Job Hunter - 导入收集的 JD")
    print("=" * 60)

    collected_dir = Path.home() / ".job_hunter" / "collected_jds"
    if not collected_dir.exists():
        print(f"\n❌ 数据目录不存在: {collected_dir}")
        print("请先用 smart_collector.py 收集一些职位")
        return 0

    job_files = sorted(collected_dir.glob("job_*.json"))
    if not job_files:
        print("\n❌ 目录中没有找到收集的 JD")
        print("请先用 smart_collector.py 收集一些职位")
        return 0

    print(f"\n找到 {len(job_files)} 个收集的职位（归属 user_id={user_id}）\n")

    db = get_db()
    classifier = Classifier()

    imported_count = 0
    for idx, job_file in enumerate(job_files, 1):
        try:
            print(f"\n处理 {idx}/{len(job_files)}: {job_file.name}")

            with open(job_file, "r", encoding="utf-8") as f:
                job_data = json.load(f)

            title = job_data.get("title", "Unknown")
            raw_text = job_data.get("raw_text", "")
            print(f"  标题: {title[:60]}")

            jd_payload = {
                "url": job_data.get("url", ""),
                "title": title,
                "company": job_data.get("company", ""),
                "location": job_data.get("location", ""),
                "raw_text": raw_text,
                "source": "smart_collector",
                "crawled_at": job_data.get("saved_at") or None,
            }

            # 分类失败不阻断入库（与 crawler/pipeline.py 一致）
            try:
                classification = classifier.classify(title=title, raw_text=raw_text)
                jd_payload["industry_tag"] = classification.get("industry_tag")
                jd_payload["function_tag"] = classification.get("function_tag")
                jd_payload["position_tag"] = classification.get("position_tag")
                jd_payload["auto_classified"] = 1
                print(f"  分类: {classification.get('position_tag')} "
                      f"(layer {classification.get('layer', '?')})")
            except Exception as exc:
                logger.warning(f"分类失败，按未分类入库: {exc}")

            jd_id = insert_user_jd(db, user_id, jd_payload)

            # 向量化失败不回滚 JD：JD 本身已可见，索引可后续用 scripts/index_jds.py 补
            try:
                n_chunks = embed_and_store_jd_chunks(db, jd_id, raw_text, user_id=user_id)
            except Exception as exc:
                n_chunks = 0
                logger.warning(f"向量化失败 {jd_id}: {exc}")

            print(f"  ✅ 已入 v2 库 (ID: {jd_id}, chunks: {n_chunks})")
            imported_count += 1

            imported_dir = collected_dir / "imported"
            imported_dir.mkdir(exist_ok=True)
            job_file.rename(imported_dir / job_file.name)

        except Exception as exc:
            logger.exception(f"导入失败: {exc}")
            print(f"  ❌ 失败: {exc}")

    print("\n" + "=" * 60)
    print(f"导入完成！成功 {imported_count}/{len(job_files)}")
    print("=" * 60)
    print(f"\n可在 Flow B / JD 库中以 user_id={user_id} 查看这些 JD。")
    return imported_count


def main():
    parser = argparse.ArgumentParser(description="导入 collector 收集的 JD 到 v2 统一库")
    parser.add_argument("--user-id", required=True,
                        help="导入 JD 的归属用户 id（必填 — 数据按用户隔离）")
    args = parser.parse_args()
    import_collected_jobs(args.user_id)


if __name__ == "__main__":
    main()
