"""打印 50 query baseline 报告。

- 5 个 NDCG=0 失败样例（按 query_id 排序）
- judge 模型 + mock fallback 数
- 评测耗时
"""
import json
from pathlib import Path
import math

src = json.loads(Path("data/eval_baseline_20260724T023722Z.json").read_text(encoding="utf-8"))
print(f"=== 50 query baseline 报告 ===")
print(f"judge model: {src['judge_model']}")
print(f"judge_strategy: {src['judge_strategy']}")
print(f"judge_api_calls: {src['judge_api_calls']}")
print(f"judge_mock_fallbacks: {src['judge_mock_fallbacks']}")
print(f"judge_real_scores: {src['judge_real_scores']}")
print(f"judge_candidate_scores: {src['judge_candidate_scores']}")
print(f"")
print(f"=== 指标 ===")
print(f"NDCG@10:    {src['ndcg_at_10']}")
print(f"Recall@10:  {src['recall_at_10']}")
print(f"MRR:        {src['mrr']}")
print(f"Hit Rate:   {src['hit_rate']}")
print(f"")
print(f"=== 分布 ===")
print(f"By source: {src['queries_by_source']}")
print(f"By form:   {src['queries_by_form']}")
print(f"By type:   {src['queries_by_type']}")
print(f"")
print(f"=== 5 失败样例（NDCG=0）===")
for f in src["sample_failures"]:
    print(f"  {f['query_id']}: {f['query'][:60]}")
    print(f"    origin_source={f.get('origin_source', 'cross')}, form={f['form']}")
    print(f"    recalled: {f['recalled_titles'][:3]}... (top 3)")