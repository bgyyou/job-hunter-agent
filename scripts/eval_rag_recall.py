"""RAG 召回质量验证脚本（v2.1 N10）。

验证思路：
1. Self-retrieval 测试：用 JD 自己的 title 查，看 top_k 里有没有这条 JD 自己的 chunks。
   理想命中率接近 100%。低命中说明 embedding/检索有问题。
2. 跨岗位语义召回：用通用 query（如"需要 Python 经验"）查，看返回 chunks 是否真的相关。
   人工抽查相关性。

输出指标：
- self-retrieval 命中率（top_k=5 时）
- sim 分布（min/median/max/mean）
- chunk_type 分布
- 跨岗位召回的 top_k 结果样例（人工评估用）

用法：
    DATABASE_URL=sqlite:///data/jobhunter_v2.db python scripts/eval_rag_recall.py
    # --sample 50  只随机抽 50 条 JD 做 self-retrieval（默认全部）
"""
from __future__ import annotations

import argparse
import random
import statistics
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from database.factory import get_db


def run_self_retrieval(db, sample_n: int, query_mode: str = "title") -> dict:
    """Self-retrieval: 用 JD 的某字段查，看 top_k 里有没有自己的 chunks。

    query_mode:
      - title: 用 JD title（短，信息量少，同类 JD 互相淹没）
      - overview: 用 raw_text 前 300 字（信息量丰富，理论上更准）
      - random_chunk: 随机取该 JD 的一个 chunk 文本作为 query（最严格，
        理论上应 100% 命中自己）
    """
    import sqlite3
    conn = sqlite3.connect("data/jobhunter_v2.db")
    rows = conn.execute(
        "SELECT id, title, raw_text FROM jds WHERE source='jobsdb_batch' AND title != '' AND deleted_at IS NULL"
    ).fetchall()
    # 同时拉每个 JD 已有的 chunks，供 random_chunk 模式用
    chunk_map: dict = {}
    chunk_rows = conn.execute(
        "SELECT jd_id, chunk_text FROM knowledge_chunks WHERE legacy=0 AND deleted_at IS NULL"
    ).fetchall()
    for jd_id, text in chunk_rows:
        chunk_map.setdefault(jd_id, []).append(text)
    conn.close()

    if sample_n and sample_n < len(rows):
        rows = random.sample(rows, sample_n)

    total = len(rows)
    hit = 0
    miss_examples = []
    sim_samples = []

    from services.retrieval_service import RetrievalService
    retriever = RetrievalService(db=db)

    for jd_id, title, raw_text in rows:
        if query_mode == "title":
            query = title
        elif query_mode == "overview":
            query = (raw_text or "")[:300]
        elif query_mode == "random_chunk":
            chunks = chunk_map.get(jd_id, [])
            if not chunks:
                continue  # 没被 index 的 JD 跳过
            query = random.choice(chunks)
        else:
            raise ValueError(f"unknown query_mode: {query_mode}")

        if not query.strip():
            continue

        results = retriever.retrieve(query, top_k=5, min_similarity=0.0)
        own_jd_ids = {r.get("metadata", {}).get("jd_id") for r in results}
        if jd_id in own_jd_ids:
            hit += 1
        else:
            miss_examples.append(f"{title[:40]} | query_mode={query_mode}")
        if results:
            sim_samples.append(max(r.get("similarity", 0) for r in results))

    valid = hit + len(miss_examples)
    hit_rate = hit / valid if valid else 0
    return {
        "total": valid,
        "hit": hit,
        "hit_rate": hit_rate,
        "miss_examples": miss_examples[:10],
        "sim_max_samples": sim_samples,
        "query_mode": query_mode,
    }


def run_cross_domain(db) -> list:
    """跨岗位语义召回：用通用 query 查，返回 top_k 结果供人工评估。"""
    from services.retrieval_service import RetrievalService
    retriever = RetrievalService(db=db)
    queries = [
        "需要 Python 编程经验的岗位",
        "machine learning AI data science",
        "product manager stakeholder agile",
        "financial analysis accounting",
        "customer facing sales marketing",
    ]
    out = []
    for q in queries:
        results = retriever.retrieve(q, top_k=3, min_similarity=0.0)
        out.append({
            "query": q,
            "results": [
                {
                    "title": (r.get("metadata", {}) or {}).get("title", "")[:50],
                    "chunk_type": r.get("chunk_type", "?"),
                    "sim": r.get("similarity", 0),
                    "text": (r.get("chunk_text") or "")[:100].replace("\n", " "),
                }
                for r in results
            ],
        })
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=0, help="self-retrieval 抽样数（0=全部）")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    parser.add_argument(
        "--query-mode",
        choices=["title", "overview", "random_chunk"],
        default="title",
        help="self-retrieval 用的 query 来源（title=JD标题 / overview=raw_text前300字 / random_chunk=随机取该JD的一个chunk）",
    )
    parser.add_argument("--skip-cross-domain", action="store_true", help="跳过跨岗位语义召回部分")
    args = parser.parse_args()

    random.seed(args.seed)
    db = get_db()

    print("=" * 60)
    print("RAG 召回质量验证 — Self-Retrieval 测试")
    print("=" * 60)
    print(f"抽样数: {'全部' if args.sample == 0 else args.sample}")
    print(f"query 来源: {args.query_mode}")

    sr = run_self_retrieval(db, args.sample if args.sample > 0 else None, args.query_mode)
    print(f"\n总测试 JD 数:  {sr['total']}")
    print(f"命中（top_k 含自己）: {sr['hit']}")
    print(f"命中率:        {sr['hit_rate']*100:.1f}%")

    if sr["sim_max_samples"]:
        sims = sr["sim_max_samples"]
        print(f"\n每条 query 的最高 sim 分布:")
        print(f"  min:    {min(sims):.3f}")
        print(f"  median: {statistics.median(sims):.3f}")
        print(f"  mean:   {statistics.mean(sims):.3f}")
        print(f"  max:    {max(sims):.3f}")

    if sr["miss_examples"]:
        print(f"\n未命中样例（前 10）:")
        for t in sr["miss_examples"]:
            print(f"  - {t}")

    if args.skip_cross_domain:
        return

    print("\n" + "=" * 60)
    print("跨岗位语义召回 — 人工评估样例")
    print("=" * 60)
    cross = run_cross_domain(db)
    for c in cross:
        print(f"\nQuery: {c['query']!r}")
        if not c["results"]:
            print("  (无结果)")
            continue
        for i, r in enumerate(c["results"], 1):
            print(f"  [{i}] sim={r['sim']:.3f} type={r['chunk_type']:14s} title={r['title']}")
            print(f"      text: {r['text']}")


if __name__ == "__main__":
    main()
