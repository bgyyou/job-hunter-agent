"""Extract 50 query baseline results from data/eval_baseline_<ts>.json to eval/baseline_50_results.jsonl.

Reads per_query_summary (10 detailed) + sample_failures (5) and writes as jsonl.
"""
import json
from pathlib import Path

SRC = Path("data/eval_baseline_20260724T023722Z.json")
OUT = Path("eval/baseline_50_results.jsonl")

src = json.loads(SRC.read_text(encoding="utf-8"))
pq_summary = src.get("per_query_summary", [])
failures = src.get("sample_failures", [])
strategy = src.get("judge_strategy", "batch_per_query")

out_lines = []
for q in pq_summary:
    qout = {k: v for k, v in q.items() if k != "judge_meta"}
    jm = q.get("judge_meta", [])
    qout["recalled_titles"] = [m.get("title") for m in jm]
    qout["judge_strategy"] = strategy
    out_lines.append(json.dumps(qout, ensure_ascii=False))

for f in failures:
    out_lines.append(json.dumps(f, ensure_ascii=False))

OUT.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
print(f"wrote {len(out_lines)} lines to {OUT}")