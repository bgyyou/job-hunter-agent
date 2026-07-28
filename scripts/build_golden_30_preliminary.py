"""Golden 30 PRELIMINARY 标签生成脚本 (M-v4-1 子任务).

用途：
读 eval/golden_30_to_annotate.jsonl，对每条 query 用 LLM judge 给 top-N candidate 打分
（1-5），然后二值化为 human_label（score >= 3 → 1 相关；< 3 → 0 不相关）。

PRELIMINARY 标签是 LLM judge 自动标的占位标签，**不是真 golden**：
- LLM_API_KEY 缺失或 API 失败 → mock fallback（词重叠启发式）
- 真人工标仍需在 eval/golden_30_to_annotate.jsonl 里手填 human_label（1-5）

输出：
- eval/golden_30_preliminary.jsonl — 30 条 query × 10 candidate × human_label (0/1)
  每个 candidate 额外带 llm_judge_score (1-5) 便于后续比较

用法：
    python scripts/build_golden_30_preliminary.py [--input ...] [--output ...]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

from eval.judge import LLMJudge, judge_batch_per_query  # noqa: E402

RELEVANCE_THRESHOLD = 3  # judge score >= 3 视为相关（与 run_eval.py 对齐）


def to_binary(score: int, threshold: int = RELEVANCE_THRESHOLD) -> int:
    """1-5 judge score → 0/1 二值化标签。"""
    return 1 if score >= threshold else 0


async def score_queries(
    queries: list[dict],
    concurrency: int = 1,
) -> list[list[int]]:
    """对每条 query 的 candidates 调 batch LLM judge，返回 scores 列表。"""
    judge = LLMJudge()
    judge_queries = [{"query_id": q["query_id"], "query": q["query_text"]} for q in queries]
    judge_cands = [
        [
            {
                "jd_id": c["jd_id"],
                "title": c["jd_title"],
                "text": c.get("jd_snippet", ""),
            }
            for c in q["candidates"]
        ]
        for q in queries
    ]
    verdicts_per_query = await judge_batch_per_query(
        judge_queries, judge_cands, concurrency=concurrency,
    )
    return [[v.score for v in vs] for vs in verdicts_per_query]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default=str(PROJECT_ROOT / "eval" / "golden_30_to_annotate.jsonl"),
        help="golden 30 骨架文件（candidates 已抽，human_label 待标）",
    )
    parser.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "eval" / "golden_30_preliminary.jsonl"),
        help="PRELIMINARY 标签输出路径",
    )
    parser.add_argument(
        "--concurrency", type=int, default=1,
        help="judge batch 并发上限（默认 1 避开 429）",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    if not input_path.exists():
        raise SystemExit(f"[ERR] 输入文件不存在: {input_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with input_path.open(encoding="utf-8") as f:
        skeleton = [json.loads(line) for line in f if line.strip()]
    print(f"[INFO] 加载 {len(skeleton)} 条 query 骨架")

    scores_per_query = asyncio.run(score_queries(skeleton, concurrency=args.concurrency))

    n_relevant_total = 0
    n_candidates_total = 0
    n_written = 0
    with output_path.open("w", encoding="utf-8") as f:
        for q, scores in zip(skeleton, scores_per_query):
            if len(scores) != len(q["candidates"]):
                print(
                    f"[WARN] {q['query_id']}: judge 返回 {len(scores)} 个分数，"
                    f"candidates {len(q['candidates'])} 个，不匹配"
                )
                continue

            candidates_out = []
            for cand, score in zip(q["candidates"], scores):
                human_label = to_binary(score)
                n_relevant_total += human_label
                n_candidates_total += 1
                candidates_out.append({
                    **cand,
                    "llm_judge_score": score,
                    "human_label": human_label,
                })

            record = {
                **q,
                "candidates": candidates_out,
                "preliminary_meta": {
                    "threshold": RELEVANCE_THRESHOLD,
                    "note": (
                        "PRELIMINARY 标签：LLM judge 二值化（score>=3 → 1）。"
                        "**不是真 golden**，待人工按 annotation_guide.md 覆盖 human_label (1-5)。"
                    ),
                },
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            n_written += 1

    print(f"[OK] 写出 {n_written} 条 query → {output_path}")
    if n_candidates_total:
        print(
            f"     总 candidate: {n_candidates_total}，"
            f"相关 (label=1): {n_relevant_total} ({n_relevant_total * 100 / n_candidates_total:.1f}%)"
        )
    print()
    print("下一步：")
    print("  - 真人工标注请改 eval/golden_30_to_annotate.jsonl（human_label 1-5）")
    print("  - 跑 scripts/verify_golden_spearman.py 算 LLM judge vs PRELIMINARY 的 Spearman")


if __name__ == "__main__":
    main()