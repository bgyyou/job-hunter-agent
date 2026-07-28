"""Golden 30 Spearman 验证脚本 (M-v4-1 子任务).

用途：
验证 LLM judge 打分与 PRELIMINARY 标签（用作"准 golden"）的一致性。
逐 query 计算 NDCG@10，最后用 Spearman 等级相关看两组 NDCG 的排序一致性。

为什么不直接算 label/score 的 Spearman？
NDCG@10 把"哪个排第一"也考虑进来，更接近评测指标本身（NDCG / MRR）。
一组 query 的 NDCG 数列之间的 Spearman，是验证 LLM judge 排序能力的最直接方式。

健康门槛：Spearman ρ ≥ 0.8（M-v4-1 评测治理定义）。

输入：
- eval/golden_30_preliminary.jsonl（含 PRELIMINARY human_label 0/1 + llm_judge_score 1-5）
  默认会复用 jsonl 里已有的 llm_judge_score；
  --regenerate-judge 时会忽略 jsonl 分数，重新调 judge_batch_per_query。

输出：
- 文本报告到 stdout
- 可选 JSON 报告：--json-output

用法：
    python scripts/verify_golden_spearman.py
    python scripts/verify_golden_spearman.py --regenerate-judge
    python scripts/verify_golden_spearman.py --json-output data/spearman_report.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
from pathlib import Path
from typing import Sequence

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

# Windows GBK 控制台 utf-8 字符兜底
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass

from eval.judge import LLMJudge, judge_batch_per_query  # noqa: E402

DEFAULT_INPUT = PROJECT_ROOT / "eval" / "golden_30_preliminary.jsonl"
DEFAULT_HEALTHY_THRESHOLD = 0.8
K_DEFAULT = 10


def dcg_at_k(relevances: Sequence[float], k: int) -> float:
    """DCG@k（与 eval/run_eval.dcg_at_k 一致）。"""
    return sum(rel / math.log2(i + 2) for i, rel in enumerate(relevances[:k]))


def ndcg_at_k(relevances: Sequence[float], k: int) -> float:
    ideal = sorted(relevances, reverse=True)[:k]
    idcg = dcg_at_k(ideal, k)
    if idcg == 0:
        return 0.0
    return dcg_at_k(relevances, k) / idcg


async def regenerate_judge_scores(
    golden_rows: list[dict],
    concurrency: int = 1,
) -> list[list[int]]:
    """重新跑 LLM judge（per-query batch），拿 1-5 scores。"""
    judge = LLMJudge()
    judge_queries = [{"query_id": r["query_id"], "query": r["query_text"]} for r in golden_rows]
    judge_cands = [
        [
            {"jd_id": c["jd_id"], "title": c["jd_title"], "text": c.get("jd_snippet", "")}
            for c in r["candidates"]
        ]
        for r in golden_rows
    ]
    verdicts_per_query = await judge_batch_per_query(
        judge_queries, judge_cands, concurrency=concurrency,
    )
    return [[v.score for v in vs] for vs in verdicts_per_query]


def compute_spearman(xs: Sequence[float], ys: Sequence[float]) -> tuple[float, float]:
    """算 Spearman 等级相关系数；scipy.stats.spearmanr 返回 (rho, p-value)。"""
    from scipy.stats import spearmanr
    rho, p = spearmanr(list(xs), list(ys))
    # NaN 保护：常数列 spearmanr 返回 NaN；视为 0
    if rho is None or (isinstance(rho, float) and math.isnan(rho)):
        rho = 0.0
    return float(rho), float(p)


def build_per_query_ndcgs(
    golden_rows: list[dict],
    judge_scores_per_query: list[list[int]],
    k: int,
    relevance_threshold: int = 3,
) -> tuple[list[float], list[float]]:
    """返回 (preliminary_ndcgs, judge_ndcgs)，一一对应。"""
    preliminary_ndcgs: list[float] = []
    judge_ndcgs: list[float] = []
    for row, judge_scores in zip(golden_rows, judge_scores_per_query):
        # PRELIMINARY 侧：直接用 human_label (0/1) 算 NDCG；None / 缺失 → 0
        rels_preliminary = [
            1 if (c.get("human_label") or 0) else 0 for c in row["candidates"][:k]
        ]
        preliminary_ndcgs.append(ndcg_at_k(rels_preliminary, k))
        # LLM judge 侧：把 score>=threshold 二值化后算 NDCG；非数字兜底为 0
        rels_judge = [
            1 if (isinstance(s, (int, float)) and s >= relevance_threshold) else 0
            for s in judge_scores[:k]
        ]
        judge_ndcgs.append(ndcg_at_k(rels_judge, k))
    return preliminary_ndcgs, judge_ndcgs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input", default=str(DEFAULT_INPUT),
        help="PRELIMINARY golden 文件路径",
    )
    parser.add_argument(
        "--k", type=int, default=K_DEFAULT,
        help="NDCG@k 的 k（默认 10）",
    )
    parser.add_argument(
        "--healthy-threshold", type=float, default=DEFAULT_HEALTHY_THRESHOLD,
        help="Spearman 健康门槛（默认 0.8）",
    )
    parser.add_argument(
        "--regenerate-judge", action="store_true",
        help="忽略 jsonl 里的 llm_judge_score，重新跑 LLM judge",
    )
    parser.add_argument(
        "--concurrency", type=int, default=1,
        help="judge batch 并发上限（默认 1 避开 429）",
    )
    parser.add_argument(
        "--json-output", default=None,
        help="可选：把报告写成 JSON 文件",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"[ERR] 输入文件不存在: {input_path}")

    with input_path.open(encoding="utf-8") as f:
        golden_rows = [json.loads(line) for line in f if line.strip()]
    print(f"[INFO] 加载 {len(golden_rows)} 条 query from {input_path}")

    # 取 judge scores（可选重新跑）
    if args.regenerate_judge:
        print("[INFO] 重新跑 LLM judge（per-query batch）...")
        judge_scores_per_query = asyncio.run(
            regenerate_judge_scores(golden_rows, concurrency=args.concurrency)
        )
        n_mock_queries = 0
        judge = LLMJudge()
        if not judge.is_available:
            n_mock_queries = len(golden_rows)
        # 简单检查是否走 mock：所有分数一致 + 模型未配置 → 提示
        if n_mock_queries:
            print(f"[WARN] LLM_API_KEY 缺失，全部 query 走 mock judge fallback")
    else:
        # 直接读 jsonl 里存的 llm_judge_score
        judge_scores_per_query = [
            [int(c.get("llm_judge_score", 0) or 0) for c in r["candidates"]]
            for r in golden_rows
        ]
        # 缺失分数兜底为 3（中位）
        judge_scores_per_query = [
            [s if s in (1, 2, 3, 4, 5) else 3 for s in scores]
            for scores in judge_scores_per_query
        ]

    preliminary_ndcgs, judge_ndcgs = build_per_query_ndcgs(
        golden_rows, judge_scores_per_query, k=args.k,
    )

    # Per-query 偏差
    per_query_diff = [p - j for p, j in zip(preliminary_ndcgs, judge_ndcgs)]

    rho, p = compute_spearman(preliminary_ndcgs, judge_ndcgs)

    healthy = rho >= args.healthy_threshold
    status = "PASS" if healthy else "WARN"

    summary = {
        "input": str(input_path),
        "n_queries": len(golden_rows),
        "k": args.k,
        "healthy_threshold": args.healthy_threshold,
        "spearman_rho": round(rho, 4),
        "spearman_p_value": round(p, 4),
        "healthy": healthy,
        "mean_preliminary_ndcg": round(sum(preliminary_ndcgs) / len(preliminary_ndcgs), 4)
        if preliminary_ndcgs else 0.0,
        "mean_judge_ndcg": round(sum(judge_ndcgs) / len(judge_ndcgs), 4)
        if judge_ndcgs else 0.0,
        "mean_abs_diff": round(sum(abs(d) for d in per_query_diff) / len(per_query_diff), 4)
        if per_query_diff else 0.0,
    }

    print()
    print("=" * 60)
    print(f"Spearman 验证报告 [{status}]")
    print("=" * 60)
    print(f"输入: {input_path}")
    print(f"query 数: {len(golden_rows)}")
    print(f"NDCG@k (k={args.k})")
    print(f"  PRELIMINARY 平均 NDCG: {summary['mean_preliminary_ndcg']}")
    print(f"  LLM judge 平均 NDCG:   {summary['mean_judge_ndcg']}")
    print(f"  平均 |PRELIMINARY - judge|: {summary['mean_abs_diff']}")
    print()
    print(f"Spearman ρ: {summary['spearman_rho']:.4f}  (健康门槛 {args.healthy_threshold})")
    print(f"p-value:    {summary['spearman_p_value']:.4f}")
    print()
    if healthy:
        print(f"[OK] ρ ≥ {args.healthy_threshold} 健康门槛，LLM judge 排序与 PRELIMINARY 一致。")
    else:
        print(
            f"[WARN] ρ < {args.healthy_threshold} 健康门槛未达；"
            f"建议：1) 真人工标替换 PRELIMINARY 后重跑；"
            f"2) 检视 PRELIMINARY mock fallback 是否影响了排序。"
        )

    # Top-5 偏差最大的 query
    if per_query_diff:
        print()
        print("Top-5 偏差最大 query（|PRELIMINARY - judge|）：")
        diff_with_id = [
            (abs(d), q["query_id"], q.get("query_text", "")[:40], p, j)
            for d, q, p, j in zip(per_query_diff, golden_rows, preliminary_ndcgs, judge_ndcgs)
        ]
        diff_with_id.sort(reverse=True)
        for diff_abs, qid, qtext, p_ndcg, j_ndcg in diff_with_id[:5]:
            print(
                f"  {qid}  |diff|={diff_abs:.2f}  "
                f"preliminary_ndcg={p_ndcg:.3f}  judge_ndcg={j_ndcg:.3f}  "
                f"q='{qtext}...'"
            )

    print("=" * 60)

    if args.json_output:
        out_path = Path(args.json_output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        report = {
            **summary,
            "preliminary_ndcgs": [round(x, 4) for x in preliminary_ndcgs],
            "judge_ndcgs": [round(x, 4) for x in judge_ndcgs],
            "per_query": [
                {
                    "query_id": r["query_id"],
                    "query_text": r.get("query_text", "")[:60],
                    "preliminary_ndcg": round(p, 4),
                    "judge_ndcg": round(j, 4),
                    "diff": round(p - j, 4),
                }
                for r, p, j in zip(golden_rows, preliminary_ndcgs, judge_ndcgs)
            ],
        }
        out_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n[OK] 报告已写入 {out_path}")


if __name__ == "__main__":
    main()