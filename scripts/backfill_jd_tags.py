# -*- coding: utf-8 -*-
"""给存量未分类 JD 补打 industry/function/position tag。

背景：classifier 在 crawler/pipeline.py 入库链路里调，但 511 份存量 JD
里有 510 份是 classifier 上线前/或通过 scripts/index_jds.py 等旁路入库的，
industry_tag = NULL → RAG 检索时 jd_industry_tag 也是 None，
导致 build_skeleton 返回的 industries_covered 永远为空。

跑 L1（规则）+ L2（TF-IDF）本地分类，秒级、无 LLM 调用。
L3 落空的 JD 保持 NULL，等后续人工/LLM 补。
"""
from __future__ import annotations

import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database.classifier import Classifier
from config.settings import settings


def main():
    db_path = settings.db_path
    print(f"DB: {db_path}")

    clf = Classifier()
    conn = sqlite3.connect(db_path)

    rows = conn.execute(
        "SELECT id, title, raw_text FROM jds "
        "WHERE industry_tag IS NULL AND deleted_at IS NULL"
    ).fetchall()
    print(f"待分类：{len(rows)} 份 JD\n")

    layer_counts = Counter()
    industry_counts = Counter()
    position_counts = Counter()
    null_count = 0

    for i, (jd_id, title, raw_text) in enumerate(rows, 1):
        result = clf.classify(title or "", raw_text or "")
        layer = result.get("layer", 3)
        layer_counts[layer] += 1
        ind = result.get("industry_tag")
        pos = result.get("position_tag")
        if ind is None:
            null_count += 1
        else:
            industry_counts[ind] += 1
            position_counts[pos] += 1

        conn.execute(
            "UPDATE jds SET industry_tag=?, function_tag=?, position_tag=?, "
            "auto_classified=1, updated_at=datetime('now') WHERE id=?",
            (ind, result.get("function_tag"), pos, jd_id),
        )

        if i % 50 == 0:
            print(f"  进度 {i}/{len(rows)}...")
            conn.commit()  # 中途 commit，挂了不丢

    conn.commit()
    conn.close()

    print(f"\n{'=' * 60}")
    print(f"完成：处理 {len(rows)} 份")
    print(f"{'=' * 60}")
    print(f"Layer 分布：L1={layer_counts[1]}  L2={layer_counts[2]}  L3 (null)={null_count}")
    print(f"\nTop 5 行业：")
    for ind, n in industry_counts.most_common(5):
        print(f"  {ind}: {n}")
    print(f"\nTop 10 岗位：")
    for pos, n in position_counts.most_common(10):
        print(f"  {pos}: {n}")
    if null_count:
        print(f"\n⚠️ {null_count} 份未能自动分类，industry_tag 保留 NULL（L3 LLM fallback 未启用）")

    return 0


if __name__ == "__main__":
    sys.exit(main())
