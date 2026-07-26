"""Build eval/queries.jsonl from real JD rows.

采样策略（2026-07-24 RAG 评测 v0）：
- 200 query，覆盖：
  - 51job / jobsdb / liepin 三源（按真实分布，51job 占大头）
  - 短（1-5 词）/ 中（6-15 词）/ 长（>15 词）各占约 1/3
- 每条 query 关联"origin_jd_id"，ground truth 自检索（self-retrieval），
  即 origin JD 自己的 chunk 视为相关。跨域检索则用 skill / role 类 query。

用法：
    python eval/build_queries.py [--out eval/queries.jsonl] [--n 200] [--seed 42]
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# 跨域 query（基于 JD 标题里常见关键词反推的 role / skill query）
# 这些 query 没有固定 origin_jd；ground truth 由 LLM judge 打分决定
CROSS_DOMAIN_QUERIES = [
    ("5年 Python 后端开发经验，熟悉 Django", None),
    ("数据分析师 SQL Python Tableau", None),
    ("产品经理 互联网 用户增长", None),
    ("金融 会计 审计 CPA", None),
    ("销售 客户经理 B2B", None),
    ("机器学习工程师 PyTorch TensorFlow", None),
    ("前端工程师 React Vue TypeScript", None),
    ("Java 开发 Spring Cloud 微服务", None),
    ("运维工程师 Linux Docker Kubernetes", None),
    ("市场经理 品牌推广 数字化营销", None),
    ("UI 设计师 Figma Sketch", None),
    ("测试工程师 Selenium 自动化", None),
    ("HR 人力资源 招聘", None),
    ("跨境电商运营 Amazon Shopify", None),
    ("内容运营 新媒体 短视频", None),
    ("财务经理 预算 成本控制", None),
    ("供应链 采购 物流管理", None),
    ("机械工程师 制造 CAD", None),
    ("护士 临床 医疗", None),
    ("教师 K12 英语 教学", None),
]


def _short_form(title: str) -> str:
    """短 query：直接用 JD title（去括号内说明）。"""
    t = re.sub(r"\([^)]*\)", "", title).strip()
    # 截断过长 title
    return t[:25].strip() or title[:25]


def _medium_form(title: str, raw: str) -> str:
    """中 query：title + raw_text 第一句要点。"""
    title = re.sub(r"\([^)]*\)", "", title).strip()
    # 取 raw_text 第一句（句号/换行切割）
    snippet = re.split(r"[。\n\.!?;]", raw or "", maxsplit=1)[0].strip()
    snippet = snippet[:30]
    if snippet and snippet not in title:
        return f"{title} {snippet}"[:60].strip()
    return title[:50]


def _long_form(title: str, raw: str) -> str:
    """长 query：title + raw_text 前 80 字 + "要求相关经验"。"""
    title = re.sub(r"\([^)]*\)", "", title).strip()
    snippet = (raw or "").replace("\n", " ")[:80].strip()
    # 拼接成口语化描述
    query = f"{title} 岗位，要求{snippet}"[:120].strip()
    return query


def build_queries(n_target: int = 200, seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    conn = sqlite3.connect("data/jobhunter_v2.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    # 拉所有有 raw_text + title 的非删 JD，按 source 分层抽样
    cur.execute(
        "SELECT id, title, source, raw_text, industry_tag, position_tag "
        "FROM jds WHERE deleted_at IS NULL AND title != '' "
        "AND source IN ('51job_batch','jobsdb_batch','liepin_batch') "
        "AND length(raw_text) >= 80"
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    # 按 source 分组，按 source 真实比例分配
    by_source: dict[str, list] = {"51job_batch": [], "jobsdb_batch": [], "liepin_batch": []}
    for r in rows:
        if r["source"] in by_source:
            by_source[r["source"]].append(r)

    # 来源配额：51job 60%, jobsdb 30%, liepin 10%（趋近真实数据）
    n_short = n_medium = n_long = n_target // 3
    # 跨域 query 固定 20 条
    n_cross = len(CROSS_DOMAIN_QUERIES)
    n_self = n_target - n_cross
    per_source = {
        "51job_batch": int(n_self * 0.6),
        "jobsdb_batch": int(n_self * 0.3),
        "liepin_batch": n_self - int(n_self * 0.6) - int(n_self * 0.3),
    }

    queries: list[dict] = []
    seen_keys: set[str] = set()

    for source, quota in per_source.items():
        candidates = by_source.get(source, [])
        rng.shuffle(candidates)
        picked = 0
        # 三种 form 轮换
        forms = ["short", "medium", "long"]
        i = 0
        for r in candidates:
            if picked >= quota:
                break
            form = forms[i % 3]
            i += 1
            if form == "short":
                q = _short_form(r["title"])
            elif form == "medium":
                q = _medium_form(r["title"], r["raw_text"])
            else:
                q = _long_form(r["title"], r["raw_text"])
            q = q.strip()
            if not q:
                continue
            # 去重
            key = q.lower()
            if key in seen_keys:
                continue
            seen_keys.add(key)
            queries.append({
                "query_id": f"q{len(queries):04d}",
                "query": q,
                "form": form,
                "origin_jd_id": r["id"],
                "origin_source": source,
                "origin_title": r["title"],
                "query_type": "self_retrieval",
            })
            picked += 1

    # 跨域 query
    for i, (q, _) in enumerate(CROSS_DOMAIN_QUERIES):
        queries.append({
            "query_id": f"q{len(queries):04d}",
            "query": q,
            "form": "long" if len(q) > 15 else ("medium" if len(q) > 5 else "short"),
            "origin_jd_id": None,
            "origin_source": None,
            "origin_title": None,
            "query_type": "cross_domain",
        })

    # 交错 source + form：避免 limit 切片只取到单一 source
    rng.shuffle(queries)
    # 重排 query_id 以保证递增
    for i, q in enumerate(queries):
        q["query_id"] = f"q{i:04d}"
    return queries


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="eval/queries.jsonl")
    parser.add_argument("--n", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    queries = build_queries(args.n, args.seed)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for q in queries:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")

    # 统计
    by_form = {}
    by_source = {}
    by_type = {}
    for q in queries:
        by_form[q["form"]] = by_form.get(q["form"], 0) + 1
        by_source[q.get("origin_source") or "cross"] = by_source.get(q.get("origin_source") or "cross", 0) + 1
        by_type[q["query_type"]] = by_type.get(q["query_type"], 0) + 1

    print(f"Wrote {len(queries)} queries to {out_path}")
    print(f"  by form:  {by_form}")
    print(f"  by source: {by_source}")
    print(f"  by type:  {by_type}")


if __name__ == "__main__":
    main()