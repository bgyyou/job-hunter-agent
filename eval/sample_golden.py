"""Golden 校准集抽样脚本 (P0-模块 6 子任务 2)

依赖: baseline 跑完后 data/rag_progress.json 中有 baseline 字段
输出: eval/golden_candidates.jsonl (50 条待标 query + 5-10 候选 JD)

抽样策略:
- 分层: source × query_length × industry 均衡
- 难度: easy (NDCG>=0.8) + hard (NDCG<=0.3) + boundary (NDCG 0.4-0.7)
- 总数: 50 条
"""

import json
import random
from collections import defaultdict
from pathlib import Path
from typing import List, Dict, Any

import argparse


def load_baseline_queries(progress_path: Path) -> List[Dict[str, Any]]:
    """从 data/rag_progress.json 读 baseline 结果（含 query + NDCG）。"""
    if not progress_path.exists():
        raise FileNotFoundError(
            f"{progress_path} 不存在. 必须先跑 baseline (子任务 1)"
        )
    data = json.loads(progress_path.read_text(encoding="utf-8"))
    if "baseline" not in data:
        raise ValueError("baseline 字段缺失. 必须先跑 baseline (子任务 1)")
    baseline = data["baseline"]
    return baseline.get("per_query_results", [])


def categorize_difficulty(ndcg: float) -> str:
    """按 NDCG 分桶."""
    if ndcg >= 0.8:
        return "easy"
    if ndcg <= 0.3:
        return "hard"
    return "boundary"


def stratified_sample(
    per_query_results: List[Dict[str, Any]],
    total: int = 50,
    easy_ratio: float = 0.4,
    hard_ratio: float = 0.3,
    boundary_ratio: float = 0.3,
    seed: int = 42,
) -> List[Dict[str, Any]]:
    """分层 + 难度抽样."""
    random.seed(seed)

    buckets = defaultdict(list)
    for q in per_query_results:
        diff = categorize_difficulty(q.get("ndcg_at_10", 0.5))
        buckets[diff].append(q)

    n_easy = int(total * easy_ratio)
    n_hard = int(total * hard_ratio)
    n_boundary = total - n_easy - n_hard

    sampled = []
    for bucket_name, n in [
        ("easy", n_easy),
        ("hard", n_hard),
        ("boundary", n_boundary),
    ]:
        candidates = buckets.get(bucket_name, [])
        if len(candidates) < n:
            print(
                f"[WARN] {bucket_name} bucket 只有 {len(candidates)} 条, "
                f"少于目标 {n} 条. 全部取."
            )
            sampled.extend(candidates)
        else:
            sampled.extend(random.sample(candidates, n))

    return sampled


def build_candidate_records(
    sampled_queries: List[Dict[str, Any]],
    jd_snippet_max_chars: int = 200,
) -> List[Dict[str, Any]]:
    """为每条 query 构造待标 record（query + 候选 JD 列表）."""
    records = []
    for i, q in enumerate(sampled_queries, start=1):
        candidates = q.get("top_10_candidates", [])[:10]
        cand_records = []
        for c in candidates:
            cand_records.append(
                {
                    "jd_id": c["jd_id"],
                    "jd_title": c["jd_title"],
                    "jd_snippet": c.get("jd_snippet", "")[:jd_snippet_max_chars],
                    "human_score": None,  # 待标
                    "human_relevance_label": None,
                }
            )
        records.append(
            {
                "query_id": f"q{i:03d}",
                "query": q["query"],
                "query_source": q.get("source", "unknown"),
                "query_length_bucket": q.get("length_bucket", "unknown"),
                "industry_hint": q.get("industry_hint", "unknown"),
                "difficulty_bucket": q.get("difficulty_bucket", "unknown"),
                "candidates": cand_records,
            }
        )
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--progress",
        default="data/rag_progress.json",
        help="baseline 结果路径",
    )
    parser.add_argument(
        "--output",
        default="eval/golden_candidates.jsonl",
        help="输出待标文件路径",
    )
    parser.add_argument("--total", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    progress_path = Path(args.progress)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[INFO] 加载 baseline: {progress_path}")
    per_query = load_baseline_queries(progress_path)
    print(f"[INFO] 加载 {len(per_query)} 条 query 结果")

    print(f"[INFO] 分层抽样 (total={args.total})")
    sampled = stratified_sample(
        per_query, total=args.total, seed=args.seed
    )
    print(f"[INFO] 抽样 {len(sampled)} 条")

    print(f"[INFO] 构造待标 records")
    records = build_candidate_records(sampled)

    print(f"[INFO] 写入 {output_path}")
    with output_path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # 统计
    by_source = defaultdict(int)
    by_bucket = defaultdict(int)
    for r in records:
        by_source[r["query_source"]] += 1
        by_bucket[r["difficulty_bucket"]] += 1
    print("[INFO] 来源分布:", dict(by_source))
    print("[INFO] 难度分布:", dict(by_bucket))
    print(f"[OK] 输出 {len(records)} 条待标 query 到 {output_path}")


if __name__ == "__main__":
    main()