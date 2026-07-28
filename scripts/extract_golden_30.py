"""Golden 30 校准集抽取脚本 (M-v4-1 子任务).

用途：
从 eval/golden_candidates.jsonl 抽 30 条 query，每条取 top-10 candidate，
生成 eval/golden_30_to_annotate.jsonl（待人工标注的"骨架"）。

注意：
- human_label=None 表示待用户标 1-5 分（按 annotation_guide.md 规则）
- 这只是骨架；用户在 eval/golden_30_to_annotate.jsonl 里手填 human_label
- 真正的"半自动"是 eval/build_golden_30_preliminary.py：用 LLM judge 占位填 PRELIMINARY 标签
"""
from __future__ import annotations

import json
import random
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CANDIDATES_PATH = PROJECT_ROOT / "eval" / "golden_candidates.jsonl"
OUTPUT_PATH = PROJECT_ROOT / "eval" / "golden_30_to_annotate.jsonl"

N_QUERIES = 30
N_CANDIDATES_PER_QUERY = 10
SEED = 42  # 可复现


def main() -> None:
    if not CANDIDATES_PATH.exists():
        raise SystemExit(
            f"[ERR] {CANDIDATES_PATH} 不存在；先跑 eval/dump_golden_candidates.py"
        )

    with CANDIDATES_PATH.open(encoding="utf-8") as f:
        candidates = [json.loads(line) for line in f if line.strip()]

    print(f"[INFO] 加载 {len(candidates)} 条 query candidates")
    if len(candidates) < N_QUERIES:
        raise SystemExit(
            f"[ERR] 只有 {len(candidates)} 条 query，少于 {N_QUERIES}；"
            f"先跑 dump_golden_candidates.py 重抽"
        )

    random.seed(SEED)
    sampled = random.sample(candidates, N_QUERIES)

    # 排序保持 query_id 升序，便于人按顺序标
    sampled.sort(key=lambda r: r["query_id"])

    n_total_candidates = 0
    n_with_origin = 0
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        for c in sampled:
            # 截前 10 个 candidate（保持原序：origin_jd 优先 + recalled top-10）
            trimmed = c["candidates"][:N_CANDIDATES_PER_QUERY]
            if any(cand.get("is_origin_jd") for cand in trimmed):
                n_with_origin += 1
            n_total_candidates += len(trimmed)

            record = {
                "query_id": c["query_id"],
                "query_text": c["query"],
                "query_source": c.get("query_source", "unknown"),
                "query_form": c.get("query_form", "unknown"),
                "origin_title": c.get("origin_title", ""),
                "origin_jd_id": c.get("origin_jd_id", ""),
                "candidates": [
                    {
                        "jd_id": cand["jd_id"],
                        "jd_title": cand["jd_title"],
                        "jd_snippet": cand.get("jd_snippet", ""),
                        "llm_judge_score": cand.get("llm_judge_score"),
                        "is_origin_jd": cand.get("is_origin_jd", False),
                        # human_label 留 None：待用户按 annotation_guide.md 打 1-5 分
                        "human_label": None,
                    }
                    for cand in trimmed
                ],
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"[OK] 写出 {N_QUERIES} 条 query → {OUTPUT_PATH}")
    print(f"     含 origin_jd: {n_with_origin}/{N_QUERIES}")
    print(f"     总 candidate: {n_total_candidates}（平均 {n_total_candidates / N_QUERIES:.1f}/query）")
    print()
    print("下一步：")
    print("  1. 打开 eval/golden_30_to_annotate.jsonl，手填每个 candidate 的 human_label（1-5）")
    print("  2. 或跑 scripts/build_golden_30_preliminary.py 拿 LLM judge 占位 PRELIMINARY")


if __name__ == "__main__":
    main()
