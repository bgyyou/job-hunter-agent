"""只跑 retrieval（不调 LLM），把 50 query 的 top-10 candidates 完整落盘。

目的：为 MRR 诊断提供 retrieval 阶段数据，避免再花 1 次 50-query LLM judge。
"""
from __future__ import annotations

import json
import sys
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from database.factory import get_db
from services.retrieval_service import RetrievalService
from eval.run_eval import enrich_candidates_with_title


def main():
    queries_path = PROJECT_ROOT / "eval" / "baseline_50_queries.jsonl"
    queries = []
    with queries_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            queries.append(json.loads(line))

    print(f"Loaded {len(queries)} queries. Running retrieval-only (no LLM judge).")

    db = get_db()
    retriever = RetrievalService(db=db)

    # 1) 拿 50 query 的完整 candidates
    rows = []
    for i, q in enumerate(queries):
        try:
            cands = retriever.retrieve(q["query"], top_k=10, min_similarity=0.0)
        except Exception as exc:
            print(f"[{i}] retrieve failed: {exc}")
            cands = []
        cands = enrich_candidates_with_title(db, cands)
        rows.append({
            "query_id": q["query_id"],
            "query": q["query"],
            "form": q.get("form"),
            "query_type": q.get("query_type"),
            "origin_jd_id": q.get("origin_jd_id"),
            "origin_source": q.get("origin_source"),
            "origin_title": q.get("origin_title"),
            "candidates": cands,
        })
        if (i + 1) % 10 == 0:
            print(f"  retrieved {i + 1}/{len(queries)}")

    # 2) 落盘
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = PROJECT_ROOT / "data"
    jsonl_path = out_dir / f"diag_candidates_{ts}.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Wrote {len(rows)} per-query records to {jsonl_path}")

    # 3) 摘要：origin_jd 在 top-1 / top-3 / top-10 的命中率
    top1_origin = 0
    top3_origin = 0
    top10_origin = 0
    cross_source_in_top1 = 0
    same_source_in_top1 = 0
    for r in rows:
        origin_jd = r["origin_jd_id"]
        for ci, c in enumerate(r["candidates"], 1):
            md = c.get("metadata", {}) or {}
            if md.get("jd_id") == origin_jd:
                if ci == 1:
                    top1_origin += 1
                if ci <= 3:
                    top3_origin += 1
                top10_origin += 1
                break
        # 跨源 in top-1
        if r["candidates"]:
            c0 = r["candidates"][0]
            md0 = c0.get("metadata", {}) or {}
            if md0.get("source") and r["origin_source"] and md0["source"] != r["origin_source"]:
                cross_source_in_top1 += 1
            else:
                same_source_in_top1 += 1

    print(f"\n=== Retrieval 阶段摘要（不依赖 LLM judge）===")
    print(f"  top-1 == origin_jd: {top1_origin}/{len(rows)} = {top1_origin/len(rows):.1%}")
    print(f"  top-3 has origin_jd: {top3_origin}/{len(rows)} = {top3_origin/len(rows):.1%}")
    print(f"  top-10 has origin_jd: {top10_origin}/{len(rows)} = {top10_origin/len(rows):.1%}")
    print(f"  top-1 cross-source: {cross_source_in_top1}/{len(rows)} = {cross_source_in_top1/len(rows):.1%}")
    print(f"  top-1 same-source: {same_source_in_top1}/{len(rows)} = {same_source_in_top1/len(rows):.1%}")
    return jsonl_path


if __name__ == "__main__":
    main()
