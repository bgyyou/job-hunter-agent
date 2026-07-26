"""Pick 50 queries from eval/queries.jsonl for baseline extension.

Strategy (from sub-agent spec, adapted to real data distribution):
- source: 51job 17 / jobsdb 17 / liepin 8 / cross_domain(no origin_source) 8
- form: short 17 / medium 17 / long 16
- type: self_retrieval 30 + cross_domain 20 (but real data has 180 self + 20 cross)

Since cross_domain queries have origin_source=None, we count them under "cross".
Distribution matches user's intent: cover all 4 categories, statistics meaningful.
"""
from __future__ import annotations

import json
import random
from collections import Counter, defaultdict
from pathlib import Path

QUERIES_PATH = Path("eval/queries.jsonl")
OUT_PATH = Path("eval/baseline_50_queries.jsonl")
SEED = 42

# 目标分布（适配实际数据：liepin 只有 18 条，cross_domain 20 条）
TARGET_SOURCE = {"51job_batch": 17, "jobsdb_batch": 17, "liepin_batch": 8, "cross": 8}
TARGET_FORM = {"short": 17, "medium": 17, "long": 16}

# 先按 source/form 平衡挑选
random.seed(SEED)

all_queries = [json.loads(line) for line in QUERIES_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]

# 把 None origin_source 归类为 "cross"
for q in all_queries:
    if q.get("origin_source") is None:
        q["_bucket_source"] = "cross"
    else:
        q["_bucket_source"] = q["origin_source"]

# 按 (source, form) 分组
buckets = defaultdict(list)
for q in all_queries:
    buckets[(q["_bucket_source"], q["form"])].append(q)

# 计算每个 (source, form) 单元应挑多少 — 按 source 配额内尽量 form 平衡
picked = []
picked_ids = set()

# 每个 source 内分配 form 配额（17/17/16 → 短中长 比例 17:17:16 = 6:6:5 当 < 18 条时）
# Liepin 8 条 → 短3 中3 长2
# Cross 8 条 → 短3 中3 长2
# 51job 17 → 短6 中6 长5
# jobsdb 17 → 短6 中6 长5
SOURCE_FORM_QUOTAS = {
    "51job_batch": {"short": 6, "medium": 6, "long": 5},
    "jobsdb_batch": {"short": 6, "medium": 6, "long": 5},
    "liepin_batch": {"short": 3, "medium": 3, "long": 2},
    "cross": {"short": 3, "medium": 3, "long": 2},
}

for source, form_quota in SOURCE_FORM_QUOTAS.items():
    for form, quota in form_quota.items():
        cands = buckets.get((source, form), [])
        random.shuffle(cands)
        chosen = cands[:quota]
        for c in chosen:
            if c["query_id"] in picked_ids:
                continue
            picked.append(c)
            picked_ids.add(c["query_id"])

# 不足 50 条时，从剩余未被选的中按剩余配额补
if len(picked) < 50:
    remaining = [q for q in all_queries if q["query_id"] not in picked_ids]
    random.shuffle(remaining)
    # 先按 source 配额补
    source_counts = Counter(q["_bucket_source"] for q in picked)
    form_counts = Counter(q["form"] for q in picked)
    for q in remaining:
        if len(picked) >= 50:
            break
        s = q["_bucket_source"]
        f = q["form"]
        # 缺哪个补哪个：优先补 source 缺额，其次 form 缺额
        s_needed = TARGET_SOURCE.get(s, 0) - source_counts.get(s, 0)
        f_needed = TARGET_FORM.get(f, 0) - form_counts.get(f, 0)
        if s_needed <= 0 and f_needed <= 0:
            continue
        picked.append(q)
        picked_ids.add(q["query_id"])
        source_counts[s] += 1
        form_counts[f] += 1

# 打乱最终顺序
random.shuffle(picked)
print(f"\nFinal count: {len(picked)}")
if len(picked) != 50:
    print("Source distribution:", Counter(q["_bucket_source"] for q in picked))
    print("Form distribution:", Counter(q["form"] for q in picked))

# 验证分布
print(f"Picked {len(picked)} queries")
print("By source:", Counter(q["_bucket_source"] for q in picked))
print("By form:", Counter(q["form"] for q in picked))
print("By query_type:", Counter(q["query_type"] for q in picked))

# 写入（去掉 _bucket_source 临时字段）
if len(picked) == 50:
    with OUT_PATH.open("w", encoding="utf-8") as f:
        for q in picked:
            q.pop("_bucket_source", None)
            f.write(json.dumps(q, ensure_ascii=False) + "\n")
    print(f"Wrote {OUT_PATH}")
else:
    print("FAILED: not 50 queries, file not written")

print(f"Wrote {OUT_PATH}")