"""完整 50 query 评测 + 落盘全部 per_query 数据（用 LLM cache，0 token 成本）。

任务允许的「第 2 次 50 query 评测」。复用 eval/run_eval.py 逻辑但全量落盘 per_query。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from database.factory import get_db
from services.retrieval_service import RetrievalService
from eval.judge import LLMJudge, JudgeVerdict
from eval.run_eval import (
    compute_metrics, RELEVANCE_THRESHOLD, enrich_candidates_with_title,
)


async def run_full(queries, top_k, concurrency):
    db = get_db()
    retriever = RetrievalService(db=db)
    judge = LLMJudge()

    t0 = time.time()
    retrieve_results = []
    for i, q in enumerate(queries):
        try:
            cands = retriever.retrieve(q["query"], top_k=top_k, min_similarity=0.0)
        except Exception as exc:
            print(f"[{i}] retrieve failed: {exc}")
            cands = []
        cands = enrich_candidates_with_title(db, cands)
        retrieve_results.append({
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

    print(f"Retrieval done in {time.time() - t0:.0f}s. Judging...")

    judge_queries = []
    judge_candidates = []
    for r in retrieve_results:
        cands_for_judge = []
        for c in r["candidates"]:
            cands_for_judge.append({
                "jd_id": c.get("metadata", {}).get("jd_id"),
                "title": c.get("metadata", {}).get("title", ""),
                "text": (c.get("chunk_text") or "")[:400],
            })
        judge_queries.append({"query_id": r["query_id"], "query": r["query"]})
        judge_candidates.append(cands_for_judge)

    from eval.judge import judge_batch_per_query
    verdicts_per_query = await judge_batch_per_query(
        judge_queries, judge_candidates, concurrency=concurrency,
    )

    n_mock = 0
    n_real = 0
    per_query_full = []
    for qi, r in enumerate(retrieve_results):
        verdicts = verdicts_per_query[qi]
        cands = r["candidates"]
        rows = []
        for ci, (c, v) in enumerate(zip(cands, verdicts)):
            md = c.get("metadata", {}) or {}
            rows.append({
                "rank": ci + 1,
                "jd_id": md.get("jd_id"),
                "title": md.get("title"),
                "source": md.get("source"),
                "industry_tag": md.get("jd_industry_tag"),
                "position_tag": md.get("jd_position_tag"),
                "similarity": c.get("similarity"),
                "rerank_score": c.get("rerank_score"),
                "ranked_score": c.get("ranked_score"),
                "judge_score": v.score,
                "is_mock": v.is_mock,
                "is_origin_jd": md.get("jd_id") == r.get("origin_jd_id"),
            })
            if v.is_mock:
                n_mock += 1
            else:
                n_real += 1
        per_query_full.append({
            "query_id": r["query_id"],
            "query": r["query"],
            "form": r.get("form"),
            "query_type": r.get("query_type"),
            "origin_jd_id": r.get("origin_jd_id"),
            "origin_source": r.get("origin_source"),
            "origin_title": r.get("origin_title"),
            "n_mock_in_top10": sum(1 for v in verdicts if v.is_mock),
            "n_relevant_in_top10": sum(1 for v in verdicts if v.score >= RELEVANCE_THRESHOLD),
            "rank_of_first_relevant": next(
                (i + 1 for i, v in enumerate(verdicts) if v.score >= RELEVANCE_THRESHOLD), None
            ),
            "rank_of_origin_jd": next(
                (i + 1 for i, row in enumerate(rows) if row["is_origin_jd"]), None
            ),
            "candidates": rows,
        })

    elapsed = time.time() - t0
    print(f"\nEval done in {elapsed:.0f}s")
    print(f"  judge mock: {n_mock}/{n_mock + n_real}")

    return per_query_full, n_mock, n_real


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--queries", default="eval/baseline_50_queries.jsonl")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--concurrency", type=int, default=6)
    args = parser.parse_args()

    queries = []
    with open(args.queries, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            queries.append(json.loads(line))
    print(f"Loaded {len(queries)} queries.")

    per_query_full, n_mock, n_real = asyncio.run(
        run_full(queries, top_k=args.top_k, concurrency=args.concurrency)
    )

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = PROJECT_ROOT / "data"
    jsonl_path = out_dir / f"diag_full_{ts}.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for row in per_query_full:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Wrote {len(per_query_full)} per-query records to {jsonl_path}")

    # 真实指标
    per_q_metrics = []
    for q in per_query_full:
        scores = [c["judge_score"] for c in q["candidates"]]
        rels = [1 if s >= RELEVANCE_THRESHOLD else 0 for s in scores]
        per_q_metrics.append({
            "scores": scores,
            "rank_of_first_relevant": next((i + 1 for i, r in enumerate(rels) if r), None),
        })
    m_real = compute_metrics(per_q_metrics, k=args.top_k)
    print(f"\n=== 真实指标（mock={n_mock}）===")
    for k, v in m_real.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
