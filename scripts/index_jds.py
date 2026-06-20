"""对 jds 表里所有未 index 的 JD 批量跑 RAG indexing（chunk + embed + 落 knowledge_chunks）。

用法：
    DATABASE_URL=sqlite:///data/jobhunter_v2.db python scripts/index_jds.py

可选 --source 过滤只 index 某来源的 JD（如 jobsdb_batch）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from database.factory import get_db
from tools.jd_indexer import embed_and_store_jd_chunks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=None, help="只 index 指定 source 的 JD（默认全部）")
    args = parser.parse_args()

    db = get_db()

    # 拉 jds 表所有未删除的 JD
    import sqlite3
    conn = sqlite3.connect("data/jobhunter_v2.db")
    sql = "SELECT id, raw_text, source FROM jds WHERE deleted_at IS NULL"
    if args.source:
        sql += " AND source = ?"
        rows = conn.execute(sql, (args.source,)).fetchall()
    else:
        rows = conn.execute(sql).fetchall()
    conn.close()

    logger.info(f"found {len(rows)} JDs to index (source={args.source or 'all'})")

    total_chunks = 0
    ok = 0
    skipped = 0
    failed = 0

    for jd_id, raw_text, source in rows:
        if not raw_text or not raw_text.strip():
            skipped += 1
            continue

        try:
            n = embed_and_store_jd_chunks(db, jd_id, raw_text)
            if n > 0:
                total_chunks += n
                ok += 1
                logger.info(f"[{source}] {jd_id[:8]} → {n} chunks")
            else:
                skipped += 1
        except Exception as exc:
            logger.error(f"[{source}] {jd_id[:8]} FAILED: {exc}")
            failed += 1

    print("\n=== RAG Indexing Result ===")
    print(f"  JDs processed:  {len(rows)}")
    print(f"  Indexed OK:     {ok}")
    print(f"  Skipped (empty):{skipped}")
    print(f"  Failed:         {failed}")
    print(f"  Total chunks:   {total_chunks}")


if __name__ == "__main__":
    main()
