"""MRR 反向跌 6.9% 根因诊断脚本（一次性，写完可丢）。

不动 retrieval 核心逻辑，只调 RetrievalService.retrieve + LLMJudge + 落盘分析。
输出:
  data/diag_mrr_<ts>.jsonl - 50 query 完整 per-candidate 详情
  data/diag_mrr_<ts>.md    - 量化分析报告
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from database.factory import get_db
from services.retrieval_service import RetrievalService
from eval.judge import LLMJudge, JudgeVerdict, _mock_judge, _parse_score_array
from eval.run_eval import compute_metrics, RELEVANCE_THRESHOLD, enrich_candidates_with_title

RELEVANCE_THRESHOLD = 3


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--queries", default="eval/baseline_50_queries.jsonl")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--no-judge", action="store_true")
    parser.add_argument("--mock-fallback-rate", type=float, default=0.0,
                        help="模拟 N% 的 query 走 mock fallback（基于 query_id hash 选）")
    args = parser.parse_args()

    queries = []
    with open(args.queries, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            queries.append(json.loads(line))
    if args.limit:
        queries = queries[:args.limit]

    print(f"Loaded {len(queries)} queries. top_k={args.top_k} no_judge={args.no_judge} mock_rate={args.mock_fallback_rate}")

    db = get_db()
    retriever = RetrievalService(db=db)
    judge = LLMJudge() if not args.no_judge else None

    # 1) Retrieval — 落 50 query 的完整 candidate 详情
    retrieve_results = []
    for i, q in enumerate(queries):
        try:
            cands = retriever.retrieve(q["query"], top_k=args.top_k, min_similarity=0.0)
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

    # 2) Judge — 落每条 candidate 的 score
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
        judge_queries.append({
            "query_id": r["query_id"],
            "query": r["query"],
        })
        judge_candidates.append(cands_for_judge)

    if judge is not None:
        from eval.judge import judge_batch_per_query
        verdicts_per_query = await judge_batch_per_query(
            judge_queries, judge_candidates, concurrency=args.concurrency,
        )
    else:
        verdicts_per_query = []
        for r, cs in zip(retrieve_results, judge_candidates):
            verdicts_per_query.append([
                _mock_judge(r["query"], c["jd_id"], c["title"], c["text"]) for c in cs
            ])

    # 3) Mock fallback simulation
    if args.mock_fallback_rate > 0:
        n_to_fallback = int(len(judge_queries) * args.mock_fallback_rate)
        # 按 query_id 字符串 hash 选（确定性）
        sorted_qids = sorted(range(len(judge_queries)), key=lambda i: judge_queries[i]["query_id"])
        fallback_idxs = set(sorted_qids[:n_to_fallback])
        for i, verdicts in enumerate(verdicts_per_query):
            if i in fallback_idxs:
                # 全部 candidates 重置为 mock judge
                cands = judge_candidates[i]
                query = judge_queries[i]["query"]
                verdicts_per_query[i] = [
                    _mock_judge(query, c["jd_id"], c["title"], c["text"]) for c in cands
                ]
        print(f"Simulated mock fallback on {n_to_fallback}/{len(judge_queries)} queries")

    # 4) 拼装 per_query 完整数据（candidate-level）
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
                "cross_lang_to_origin": (
                    md.get("jd_industry_tag") and r.get("origin_source") == "jobsdb_batch"
                    and md.get("jd_industry_tag") != "互联网"  # jobsdb 多为英文，归一化不可靠
                ),
            })
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

    # 5) 落盘
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = PROJECT_ROOT / "data"
    jsonl_path = out_dir / f"diag_mrr_{ts}.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for row in per_query_full:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Wrote {len(per_query_full)} per-query records to {jsonl_path}")

    # 6) 计算核心指标 — 用真实 judge scores
    per_query_for_metrics = []
    for q in per_query_full:
        scores = [c["judge_score"] for c in q["candidates"]]
        rels = [1 if s >= RELEVANCE_THRESHOLD else 0 for s in scores]
        per_query_for_metrics.append({
            "scores": scores,
            "rank_of_first_relevant": next((i + 1 for i, r in enumerate(rels) if r), None),
        })
    m_real = compute_metrics(per_query_for_metrics, k=args.top_k)
    print(f"\n=== 当前真实指标（mock_rate={args.mock_fallback_rate}）===")
    for k, v in m_real.items():
        print(f"  {k}: {v}")

    # 7) 模拟"去掉 mock fallback 影响"：把 is_mock=True 的 candidate 强制 score=1（噪声）
    if args.mock_fallback_rate > 0:
        per_query_no_mock = []
        for q in per_query_full:
            scores = []
            for c in q["candidates"]:
                if c["is_mock"]:
                    scores.append(1)  # 把 mock 假分强制降为 1（噪声）
                else:
                    scores.append(c["judge_score"])
            rels = [1 if s >= RELEVANCE_THRESHOLD else 0 for s in scores]
            per_query_no_mock.append({
                "scores": scores,
                "rank_of_first_relevant": next((i + 1 for i, r in enumerate(rels) if r), None),
            })
        m_no_mock = compute_metrics(per_query_no_mock, k=args.top_k)
        print(f"\n=== 模拟：去掉 mock fallback（mock→1）===")
        for k, v in m_no_mock.items():
            print(f"  {k}: {v}")
        # MRR 变化
        delta_mrr_no_mock = m_no_mock["mrr"] - m_real["mrr"]
        print(f"\n  ΔMRR (去 mock): {delta_mrr_no_mock:+.4f}")

    # 8) 模拟"去掉 cross-lang 候选"：把 industry_tag 跟 origin_source 不一致（粗略）的 candidate 强制 similarity→0
    # 简化定义：origin_source == "jobsdb_batch" 视为英文 JD；如果 candidate jd_industry_tag 标记
    # 不明确（NULL），保守不剔除。这里用"origin_source 跟 candidate.source 不同"作 weak proxy。
    per_query_no_cross = []
    for q in per_query_full:
        scores = []
        for c in q["candidates"]:
            if c["source"] and q["origin_source"] and c["source"] != q["origin_source"]:
                scores.append(1)  # 跨源 → 噪声
            else:
                scores.append(c["judge_score"])
        rels = [1 if s >= RELEVANCE_THRESHOLD else 0 for s in scores]
        per_query_no_cross.append({
            "scores": scores,
            "rank_of_first_relevant": next((i + 1 for i, r in enumerate(rels) if r), None),
        })
    m_no_cross = compute_metrics(per_query_no_cross, k=args.top_k)
    print(f"\n=== 模拟：去掉 cross-source 候选（cross→1）===")
    for k, v in m_no_cross.items():
        print(f"  {k}: {v}")
    delta_mrr_no_cross = m_no_cross["mrr"] - m_real["mrr"]
    print(f"\n  ΔMRR (去 cross-source): {delta_mrr_no_cross:+.4f}")

    # 9) 模拟"同时去掉 mock + cross-source"
    per_query_clean = []
    for q in per_query_full:
        scores = []
        for c in q["candidates"]:
            if c["is_mock"] or (c["source"] and q["origin_source"] and c["source"] != q["origin_source"]):
                scores.append(1)
            else:
                scores.append(c["judge_score"])
        rels = [1 if s >= RELEVANCE_THRESHOLD else 0 for s in scores]
        per_query_clean.append({
            "scores": scores,
            "rank_of_first_relevant": next((i + 1 for i, r in enumerate(rels) if r), None),
        })
    m_clean = compute_metrics(per_query_clean, k=args.top_k)
    print(f"\n=== 模拟：mock+cross 同时去掉 ===")
    for k, v in m_clean.items():
        print(f"  {k}: {v}")
    delta_mrr_clean = m_clean["mrr"] - m_real["mrr"]
    print(f"\n  ΔMRR (clean): {delta_mrr_clean:+.4f}")

    # 10) Top-1 详细：top-1 是 origin_jd 的占比
    top1_is_origin = sum(1 for q in per_query_full if (q["rank_of_origin_jd"] == 1))
    top1_is_relevant = sum(1 for q in per_query_full if (q["rank_of_first_relevant"] == 1))
    top3_has_origin = sum(1 for q in per_query_full if (q["rank_of_origin_jd"] and q["rank_of_origin_jd"] <= 3))
    print(f"\n=== Top-1 命中率 ===")
    print(f"  top-1 == origin_jd: {top1_is_origin}/{len(per_query_full)} = {top1_is_origin/len(per_query_full):.1%}")
    print(f"  top-1 == 任意 relevant (>=3): {top1_is_relevant}/{len(per_query_full)} = {top1_is_relevant/len(per_query_full):.1%}")
    print(f"  top-3 has origin_jd: {top3_has_origin}/{len(per_query_full)} = {top3_has_origin/len(per_query_full):.1%}")

    # 11) 找 MRR 跌最大（前 5）的 query：模拟"原 baseline"（无 mock 干预 + 当前 retrieval）
    # 当前无 mock，所以 m_real 就是"无 mock" 状态。无法直接对比 "backfill 前" 的 retrieval。
    # 但可以用 origin_jd 是否在 top-1 来拆"理想 MRR" vs "实际 MRR"
    mrr_perfect_if_origin_top1 = sum(
        1.0 / q["rank_of_origin_jd"] if q["rank_of_origin_jd"] else 0.0
        for q in per_query_full
    ) / len(per_query_full)
    print(f"\n=== 理想 MRR（如果 origin_jd 都在其出现的位置）===")
    print(f"  perfect MRR (origin_jd as relevant): {mrr_perfect_if_origin_top1:.4f}")
    print(f"  actual MRR (judge >=3 relevant): {m_real['mrr']:.4f}")

    return jsonl_path, m_real


if __name__ == "__main__":
    asyncio.run(main())
