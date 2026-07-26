"""Run baseline RAG recall eval (P0-模块 6 子任务 1, 2026-07-24).

流程：
1. 加载 eval/queries.jsonl
2. 对每个 query 调 RetrievalService.retrieve(top_k=10)
3. 调 LLM-as-judge 给每个 query × 10 候选打分（1-5）
4. 计算 NDCG@10 / Recall@10 / MRR / Hit Rate
5. 写 data/rag_progress.json + data/eval_baseline_<ts>.json
6. 打印人类可读摘要

相关判定阈值：judge score >= 3 视为相关。

用法：
    python eval/run_eval.py [--queries eval/queries.jsonl] [--top-k 10]
                            [--concurrency 6] [--limit 200] [--no-judge]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import sqlite3
import sys
import time
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

from database.factory import get_db  # noqa: E402
from services.retrieval_service import RetrievalService  # noqa: E402

from eval.judge import LLMJudge, JudgeVerdict  # noqa: E402


RELEVANCE_THRESHOLD = 3  # judge >= 3 视为相关
TOP_K_DEFAULT = 10


def dcg_at_k(relevances: list[int], k: int) -> float:
    return sum(rel / math.log2(i + 2) for i, rel in enumerate(relevances[:k]))


def ndcg_at_k(relevances: list[int], k: int) -> float:
    ideal = sorted(relevances, reverse=True)[:k]
    idcg = dcg_at_k(ideal, k)
    if idcg == 0:
        return 0.0
    return dcg_at_k(relevances, k) / idcg


def compute_metrics(per_query: list[dict], k: int = 10) -> dict:
    """per_query = [{scores: [int], rank_of_first_relevant: int|None}]"""
    n = len(per_query)
    if n == 0:
        return {"ndcg_at_10": 0.0, "recall_at_10": 0.0, "mrr": 0.0, "hit_rate": 0.0}
    ndcgs, recalls, mrrs, hits = [], [], [], []
    for q in per_query:
        scores = q.get("scores", [])
        # binary relevance
        rels = [1 if s >= RELEVANCE_THRESHOLD else 0 for s in scores[:k]]
        ndcgs.append(ndcg_at_k(rels, k))
        # Recall@10 = 召回数 / 总相关数
        total_relevant_in_top_k = sum(rels)
        # 我们只有 top-k 的相关性；recall 近似 = rels_in_top_k / max(rel_in_top_k, min_assumed_total)
        # 在 self-retrieval 场景下真实相关数 ≥ 1（origin jd 自己的 chunk 应被召回）
        # 取 top-k 内召回数即可，记 Recall = rels_in_top_k / max(1, 真实相关数)
        # 由于我们不知道"全集相关数"（ground truth 不完整），改用"top-k 命中率"作为 recall proxy：
        #   Recall@k_proxy = 1 if at least 1 relevant in top-k else 0
        # 但这与 hit_rate 重复。改用：在 origin_jd 存在的 self-retrieval 场景下，
        # recall_proxy = (top-k 中相关数) / min(10, 期望相关数=5)
        # 由于 judge 1-5 是 absolute relevance，不依赖 origin_jd，我们用 simpler proxy：
        #   Recall@k = |relevant in top-k| / k  （归一化）
        # 这反映 top-k 中相关 JD 的密度。
        recalls.append(total_relevant_in_top_k / k)
        # MRR：第一个相关 JD 的倒数排名
        first_rel = q.get("rank_of_first_relevant")
        if first_rel is not None and first_rel > 0:
            mrrs.append(1.0 / first_rel)
        else:
            mrrs.append(0.0)
        # Hit Rate：top-k 至少一个相关
        hits.append(1 if total_relevant_in_top_k > 0 else 0)
    return {
        "ndcg_at_10": round(sum(ndcgs) / n, 4),
        "recall_at_10": round(sum(recalls) / n, 4),
        "mrr": round(sum(mrrs) / n, 4),
        "hit_rate": round(sum(hits) / n, 4),
        "n_queries": n,
    }


def load_queries(path: Path) -> list[dict]:
    queries = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            queries.append(json.loads(line))
    return queries


def enrich_candidates_with_title(db, candidates: list[dict]) -> list[dict]:
    """把 candidate 的 jd_id 反查 title / source，便于 judge 看到完整信息。"""
    jd_ids = list({c.get("metadata", {}).get("jd_id") for c in candidates if c.get("metadata", {}).get("jd_id")})
    if not jd_ids:
        return candidates
    placeholders = ",".join(["?"] * len(jd_ids))
    conn = sqlite3.connect("data/jobhunter_v2.db")
    try:
        rows = conn.execute(
            f"SELECT id, title, source FROM jds WHERE id IN ({placeholders})",
            jd_ids,
        ).fetchall()
    finally:
        conn.close()
    title_map = {r[0]: {"title": r[1], "source": r[2]} for r in rows}
    for c in candidates:
        jd_id = c.get("metadata", {}).get("jd_id")
        if jd_id and jd_id in title_map:
            c.setdefault("metadata", {})["title"] = title_map[jd_id]["title"]
            c.setdefault("metadata", {})["source"] = title_map[jd_id]["source"]
    return candidates


async def run(
    queries: list[dict],
    top_k: int = TOP_K_DEFAULT,
    concurrency: int = 6,
    use_judge: bool = True,
    db=None,
) -> dict:
    if db is None:
        db = get_db()
    retriever = RetrievalService(db=db)
    judge = LLMJudge() if use_judge else None

    t0 = time.time()
    retrieve_results: list[dict] = []
    for i, q in enumerate(queries):
        try:
            candidates = retriever.retrieve(q["query"], top_k=top_k, min_similarity=0.0)
        except Exception as exc:
            print(f"[{i}] retrieve failed for {q['query_id']}: {exc}")
            candidates = []
        candidates = enrich_candidates_with_title(db, candidates)
        retrieve_results.append({
            "query_id": q["query_id"],
            "query": q["query"],
            "form": q["form"],
            "query_type": q["query_type"],
            "origin_jd_id": q.get("origin_jd_id"),
            "origin_source": q.get("origin_source"),
            "candidates": candidates,
        })
        if (i + 1) % 20 == 0:
            print(f"  retrieved {i + 1}/{len(queries)} ({time.time() - t0:.0f}s)")

    print(f"Retrieval done in {time.time() - t0:.0f}s. Now judging...")

    # Judge — batch per query（一次 LLM 调用打 10 个候选，10× call 缩减）
    judge_queries: list[dict] = []
    judge_candidates: list[list[dict]] = []
    for r in retrieve_results:
        cands_for_judge = []
        for c in r["candidates"]:
            cands_for_judge.append({
                "jd_id": c.get("metadata", {}).get("jd_id"),
                "title": c.get("metadata", {}).get("title", "(no title)"),
                "text": (c.get("chunk_text") or "")[:400],
            })
        judge_queries.append({
            "query_id": r["query_id"],
            "query": r["query"],
        })
        judge_candidates.append(cands_for_judge)

    if use_judge and judge is not None and any(judge_candidates):
        from eval.judge import judge_batch_per_query
        verdicts_per_query: list[list[JudgeVerdict]] = await judge_batch_per_query(
            judge_queries, judge_candidates, concurrency=concurrency,
        )
    else:
        from eval.judge import _mock_judge
        verdicts_per_query = []
        for r, cs in zip(retrieve_results, judge_candidates):
            verdicts_per_query.append([
                _mock_judge(r["query"], c["jd_id"], c["title"], c["text"]) for c in cs
            ])

    # aggregate scores per query
    per_query_scores: dict[int, list[int]] = defaultdict(list)
    per_query_judge_meta: dict[int, list[dict]] = defaultdict(list)
    n_mock = 0
    for qi, verdicts in enumerate(verdicts_per_query):
        for ci, v in enumerate(verdicts):
            per_query_scores[qi].append(v.score)
            per_query_judge_meta[qi].append({
                "candidate_idx": ci,
                "jd_id": v.candidate_jd_id,
                "title": v.candidate_title,
                "score": v.score,
                "is_mock": v.is_mock,
            })
            if v.is_mock:
                n_mock += 1

    # build per-query results
    per_query_results = []
    failures = []
    for qi, r in enumerate(retrieve_results):
        scores = per_query_scores.get(qi, [])
        rels = [1 if s >= RELEVANCE_THRESHOLD else 0 for s in scores]
        rank_of_first = next((i + 1 for i, x in enumerate(rels) if x), None)
        per_query_results.append({
            "query_id": r["query_id"],
            "query": r["query"],
            "scores": scores,
            "rank_of_first_relevant": rank_of_first,
            "n_relevant_in_top_k": sum(rels),
            "judge_meta": per_query_judge_meta.get(qi, []),
        })
        # 失败样例：hit_rate == 0 OR 全部 ≤ 2
        if sum(rels) == 0:
            titles = [m["title"] for m in per_query_judge_meta.get(qi, [])]
            failures.append({
                "query_id": r["query_id"],
                "query": r["query"],
                "form": r["form"],
                "query_type": r["query_type"],
                "origin_jd_id": r.get("origin_jd_id"),
                "origin_source": r.get("origin_source"),
                "recalled_titles": titles,
                "recalled_jd_ids": [m["jd_id"] for m in per_query_judge_meta.get(qi, [])],
            })

    metrics = compute_metrics(per_query_results, k=top_k)

    # source 分布
    source_counts = defaultdict(int)
    for q in queries:
        source_counts[q.get("origin_source") or "cross"] += 1
    form_counts = defaultdict(int)
    for q in queries:
        form_counts[q["form"]] += 1
    type_counts = defaultdict(int)
    for q in queries:
        type_counts[q["query_type"]] += 1

    n_judge_total = sum(len(v) for v in verdicts_per_query)
    n_judge_real = sum(1 for vs in verdicts_per_query for v in vs if not v.is_mock)
    n_judge_calls_llm = len(verdicts_per_query)  # batch per query = 1 LLM call each
    n_judge_calls_mock = sum(1 for vs in verdicts_per_query if all(v.is_mock for v in vs))

    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "judge_model": judge.model if (judge and judge.is_available) else "MOCK",
        "judge_is_mock": not (judge and judge.is_available) or n_judge_calls_mock > 0,
        "judge_strategy": "batch_per_query",
        "judge_api_calls": n_judge_calls_llm,
        "judge_candidate_scores": n_judge_total,
        "judge_real_scores": n_judge_real,
        "judge_mock_fallbacks": n_judge_calls_mock,
        "top_k": top_k,
        "num_queries": len(queries),
        "n_zero_relevant_in_top10": len(failures),
        "queries_by_source": dict(source_counts),
        "queries_by_form": dict(form_counts),
        "queries_by_type": dict(type_counts),
        **metrics,
        "sample_failures": failures[:5],
        "per_query_summary": per_query_results[:10],  # 前 10 条作为样例
    }

    elapsed = time.time() - t0
    print(f"\nEval done in {elapsed:.0f}s")
    print(f"  judge model: {summary['judge_model']}")
    print(f"  judge strategy: {summary['judge_strategy']}")
    print(f"  judge API calls (per-query batch): {summary['judge_api_calls']}")
    print(f"  judge mock queries: {summary['judge_mock_fallbacks']}/{summary['judge_api_calls']}")
    print(f"  NDCG@{top_k}:    {summary[f'ndcg_at_{top_k}']:.4f}")
    print(f"  Recall@{top_k}:  {summary[f'recall_at_{top_k}']:.4f}  (proxy = relevant_in_top_k / k)")
    print(f"  MRR:             {summary['mrr']:.4f}")
    print(f"  Hit Rate:        {summary['hit_rate']:.4f}")
    print(f"  Failures (no relevant in top-{top_k}): {len(failures)}/{len(queries)}")
    return summary


def write_outputs(summary: dict, queries_path: Path, out_dir: Path = Path("data")):
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ts_iso = summary["timestamp"]

    # 1) eval_baseline_<ts>.json (full)
    full_path = out_dir / f"eval_baseline_{ts}.json"
    full_payload = {
        **summary,
        "queries_source": str(queries_path),
        "all_per_query": [],  # 留空，避免大文件；需要时重跑
    }
    full_path.write_text(json.dumps(full_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # 2) data/rag_progress.json
    progress_path = out_dir / "rag_progress.json"
    progress = {}
    if progress_path.exists():
        try:
            progress = json.loads(progress_path.read_text(encoding="utf-8"))
        except Exception:
            progress = {}
    progress["baseline"] = {
        "timestamp": ts_iso,
        "judge_model": summary["judge_model"],
        "judge_strategy": summary["judge_strategy"],
        "judge_is_mock": summary["judge_is_mock"],
        "judge_api_calls": summary["judge_api_calls"],
        "judge_candidate_scores": summary["judge_candidate_scores"],
        "judge_real_scores": summary["judge_real_scores"],
        "judge_mock_fallbacks": summary["judge_mock_fallbacks"],
        "num_queries": summary["num_queries"],
        "queries_by_source": summary["queries_by_source"],
        "queries_by_form": summary["queries_by_form"],
        "queries_by_type": summary["queries_by_type"],
        "top_k": summary["top_k"],
        "ndcg_at_10": summary["ndcg_at_10"],
        "recall_at_10": summary["recall_at_10"],
        "mrr": summary["mrr"],
        "hit_rate": summary["hit_rate"],
        "n_zero_relevant_in_top10": summary["n_zero_relevant_in_top10"],
        "sample_failures": summary["sample_failures"],
    }
    progress_path.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nWrote:\n  {full_path}\n  {progress_path}")
    return full_path, progress_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--queries", default="eval/queries.jsonl")
    parser.add_argument("--top-k", type=int, default=TOP_K_DEFAULT)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--limit", type=int, default=0, help="限制 query 数（0=全部）")
    parser.add_argument("--no-judge", action="store_true", help="跳过 LLM judge，用纯 mock")
    args = parser.parse_args()

    queries_path = Path(args.queries)
    queries = load_queries(queries_path)
    if args.limit and args.limit < len(queries):
        queries = queries[: args.limit]

    summary = asyncio.run(run(
        queries=queries,
        top_k=args.top_k,
        concurrency=args.concurrency,
        use_judge=not args.no_judge,
    ))

    write_outputs(summary, queries_path)


if __name__ == "__main__":
    main()