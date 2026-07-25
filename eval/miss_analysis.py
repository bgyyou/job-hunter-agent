"""失败样例预分析 (P0-模块 6 子任务 2 / backfill 前置)

输入：
- eval/baseline_50_results.jsonl — 15 条有 LLM judge 评分的 query
- data/eval_baseline_<最新>.json — 完整 baseline 含 5 条 sample_failures
- data/jobhunter_v2.db — 真实 JD source / industry / position（决定 cross-language gap）

输出：
- data/miss_analysis_<ts>.md — 按 form/source/cross-language gap 分类的失败 query 分析

跑法：python eval/miss_analysis.py
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_results(path: Path) -> List[Dict[str, Any]]:
    """读 jsonl → list of records（不按 qid dedup，让上层合并）"""
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out


def load_jd_index(db_path: Path) -> Dict[str, Dict[str, Any]]:
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT id, title, source, industry_tag, position_tag FROM jds"
    ).fetchall()
    out = {}
    for jd_id, title, source, industry, position in rows:
        out[jd_id] = {
            "title": title or "",
            "source": source or "",
            "industry": industry or "",
            "position": position or "",
        }
    conn.close()
    return out


def is_zh(text: str) -> bool:
    if not text:
        return False
    cjk = sum(1 for c in text if "一" <= c <= "鿿" or "　" <= c <= "〿")
    return cjk / max(len(text), 1) > 0.2


def classify_failure(
    q: Dict[str, Any],
    result: Optional[Dict[str, Any]],
    jd_index: Dict[str, Dict[str, Any]],
) -> str:
    """分类失败原因。

    返回：
    - "cross_language_zh_to_en": query 是中文，召回全是英文 jobsdb（翻译后预计救活）
    - "cross_language_en_to_zh": query 是英文，召回全是中文 liepin（重写 query 救）
    - "same_language_but_unrelated": 语种对齐但内容无关（chunk 切分 / 数据覆盖问题）
    - "no_recall_at_all": top-10 完全空 / 完全没相关
    - "unknown": 兜底
    """
    if not result:
        return "no_result_record"

    query_text = q["query"]
    query_lang = "zh" if is_zh(query_text) else "en"

    recalled_ids = result.get("recalled_jd_ids", [])
    if not recalled_ids:
        return "no_recall_at_all"

    recalled_sources = Counter(jd_index.get(jid, {}).get("source", "") for jid in recalled_ids)

    zh_ratio = (recalled_sources.get("51job_batch", 0) + recalled_sources.get("liepin_batch", 0)) / sum(
        recalled_sources.values()
    )
    en_ratio = recalled_sources.get("jobsdb_batch", 0) / sum(recalled_sources.values())

    if query_lang == "zh" and en_ratio > 0.7:
        return "cross_language_zh_to_en"
    if query_lang == "en" and zh_ratio > 0.7:
        return "cross_language_en_to_zh"
    if query_lang == "zh" and zh_ratio > 0.7:
        return "same_language_but_unrelated"
    return "mixed"


def main():
    queries_path = PROJECT_ROOT / "eval" / "baseline_50_queries.jsonl"
    results_path = PROJECT_ROOT / "eval" / "baseline_50_results.jsonl"
    db_path = PROJECT_ROOT / "data" / "jobhunter_v2.db"

    # 找最新 baseline JSON
    baseline_jsons = sorted((PROJECT_ROOT / "data").glob("eval_baseline_*.json"))
    if not baseline_jsons:
        raise SystemExit("no eval_baseline_*.json found")
    baseline_json_path = baseline_jsons[-1]
    print(f"[INFO] 使用 baseline: {baseline_json_path.name}")

    baseline = json.loads(baseline_json_path.read_text(encoding="utf-8"))
    sample_failures = {f["query_id"]: f for f in baseline.get("sample_failures", [])}

    queries_list = load_results(queries_path)
    results_list = load_results(results_path)
    # 转 queries 为 {qid: rec} 便于按 qid 查
    queries = {r["query_id"]: r for r in queries_list}
    jd_index = load_jd_index(db_path)

    # 合并：results 里按 qid 聚合（合并多 entry 字段），再叠 sample_failures
    all_records = {}
    for r in results_list:
        qid = r["query_id"]
        q = queries.get(qid, {})
        merged = {**q, **r}
        if qid in all_records:
            # 合并字段：保留所有 unique keys（后写的不覆盖先有的）
            all_records[qid] = {**all_records[qid], **merged}
        else:
            all_records[qid] = merged

    for qid, f in sample_failures.items():
        if qid in all_records:
            all_records[qid] = {**all_records[qid], **f}
        else:
            all_records[qid] = {**queries.get(qid, {}), **f}

    print(f"[INFO] 总合并记录: {len(all_records)} 条")

    # 分类
    classified = defaultdict(list)
    for qid, rec in all_records.items():
        cat = classify_failure(rec, rec, jd_index)
        rec["_failure_category"] = cat
        classified[cat].append(rec)

    # 统计
    n_zero = sum(1 for r in all_records.values() if r.get("n_relevant_in_top_k") == 0)
    n_low = sum(
        1 for r in all_records.values()
        if (r.get("n_relevant_in_top_k") or 0) > 0 and (r.get("n_relevant_in_top_k") or 0) <= 2
    )
    n_weak = n_zero + n_low  # 真正"弱"的 query，分母要用这个

    # 写报告
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = PROJECT_ROOT / "data" / f"miss_analysis_{ts}.md"
    lines = []
    lines.append(f"# RAG 失败样例分析 ({ts})")
    lines.append("")
    lines.append("## 0. 输入")
    lines.append(f"- baseline: `{baseline_json_path.name}`")
    lines.append(f"- 合并记录: {len(all_records)} 条 query（results 15 + sample_failures 5 去重）")
    lines.append(f"- 完整 50 query baseline: NDCG@10={baseline.get('ndcg_at_10'):.4f}, "
                 f"Recall@10={baseline.get('recall_at_10'):.4f}, MRR={baseline.get('mrr'):.4f}, "
                 f"Hit Rate={baseline.get('hit_rate')}, n_zero_relevant_in_top10={baseline.get('n_zero_relevant_in_top10')}")
    lines.append("")
    lines.append("## 1. 已知失败 case（合并样本）分布")
    lines.append("")
    lines.append(f"- 完全 miss（n_relevant_in_top_k=0）: **{n_zero}** 条")
    lines.append(f"- 弱召回（n_relevant 1-2）: **{n_low}** 条")
    lines.append("")
    lines.append("### 按失败原因分类")
    lines.append("")
    lines.append("| 分类 | 数量 | 翻译 backfill 是否能救活 | 含义 |")
    lines.append("|---|---|---|---|")
    descriptions = {
        "cross_language_zh_to_en": (
            "能救",
            "query 中文但召回全英文 jobsdb → 翻译后英文 chunks 入中文向量空间，召回命中",
        ),
        "cross_language_en_to_zh": (
            "部分能救",
            "query 英文但召回中文 → 需要 query 改写（HyDE / Multi-Query）反向翻译",
        ),
        "same_language_but_unrelated": (
            "救不了",
            "语种对齐但 top-10 内容无关 → 数据覆盖 / chunk 切分问题（模块 1/2）",
        ),
        "no_recall_at_all": (
            "不确定",
            "top-10 完全空 / 完全无相关 → 数据缺失",
        ),
        "mixed": (
            "部分能救",
            "混合来源 → 部分救",
        ),
        "no_result_record": (
            "N/A",
            "无 result 记录，跳过",
        ),
    }
    for cat, recs in sorted(classified.items(), key=lambda x: -len(x[1])):
        verdict, meaning = descriptions.get(cat, ("?", "?"))
        lines.append(f"| {cat} | {len(recs)} | **{verdict}** | {meaning} |")
    lines.append("")
    lines.append("## 2. 按 form / source 分布")
    lines.append("")
    lines.append("| 维度 | 分布 |")
    lines.append("|---|---|")
    form_counter = Counter()
    source_counter = Counter()
    for r in all_records.values():
        form_counter[r.get("form", "unknown")] += 1
        source_counter[r.get("origin_source", "unknown")] += 1
    for form, n in sorted(form_counter.items(), key=lambda x: -x[1]):
        lines.append(f"| form={form} | {n} |")
    for src, n in sorted(source_counter.items(), key=lambda x: -x[1]):
        lines.append(f"| origin_source={src} | {n} |")
    lines.append("")
    lines.append("## 3. 详细样例（每类前 3 条）")
    lines.append("")
    for cat, recs in sorted(classified.items(), key=lambda x: -len(x[1])):
        if not recs or cat == "no_result_record":
            continue
        lines.append(f"### {cat} ({len(recs)} 条)")
        lines.append("")
        for rec in recs[:3]:
            qid = rec.get("query_id", "?")
            q = rec.get("query", "")[:120]
            n_rel = rec.get("n_relevant_in_top_k", "?")
            titles = rec.get("recalled_titles", [])[:3]
            scores = rec.get("scores", [])[:3] if rec.get("scores") else []
            origin_src = rec.get("origin_source", "?")
            origin_title = rec.get("origin_title", "")[:60]
            lines.append(f"- **{qid}** [origin={origin_src}, n_relevant={n_rel}]")
            lines.append(f"  - query: `{q}`")
            lines.append(f"  - origin_title: `{origin_title}`")
            lines.append(f"  - recalled (top-3): `{titles}`" + (f" llm_scores={scores}" if scores else ""))
            lines.append("")

    lines.append("## 4. 结论与对后续模块的 input")
    lines.append("")
    n_cross_lang = (
        len(classified.get("cross_language_zh_to_en", []))
        + len(classified.get("cross_language_en_to_zh", []))
    )
    n_same_lang = len(classified.get("same_language_but_unrelated", []))
    n_no_recall = len(classified.get("no_recall_at_all", []))
    lines.append(f"- 已知弱召回 query 总数（n_zero + n_low）: **{n_weak}** 条")
    lines.append(f"- **Cross-language gap**: {n_cross_lang} 条（{(n_cross_lang / max(n_weak, 1) * 100):.0f}% of weak）")
    lines.append(f"- **同语种但内容无关**: {n_same_lang} 条（{(n_same_lang / max(n_weak, 1) * 100):.0f}% of weak）")
    lines.append(f"- **完全无召回**: {n_no_recall} 条（{(n_no_recall / max(n_weak, 1) * 100):.0f}% of weak）")
    lines.append("")
    lines.append("### 翻译 backfill 预期效果")
    lines.append("")
    lines.append("翻译能把 `cross_language_zh_to_en` 这类 query 从\"全英文召回\"变成\"中文召回\"，")
    lines.append("但 recall 是否真命中取决于：")
    lines.append("1. 翻译后的中文 chunk 语义保真度（MiniMax-M3 翻译质量待验）")
    lines.append("2. origin_jd 是否真的在 top-50 候选里（rerank 之前就要有）")
    lines.append("")
    lines.append("### 给模块 1 / 模块 2 的 input（翻译救不了的）")
    lines.append("")
    lines.append("`same_language_but_unrelated` 类失败需要：")
    lines.append("- 模块 1：数据清洗（特殊格式 JD 解析、噪音 chunk 标记）")
    lines.append("- 模块 2：chunk 切分优化（overlap、contextual retrieval）")
    lines.append("- 候选扩展：candidate_k 加大，或 query 改写")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] 报告写入: {output_path}")
    print()
    print("=== 摘要 ===")
    for cat, recs in sorted(classified.items(), key=lambda x: -len(x[1])):
        print(f"  {cat}: {len(recs)}")


if __name__ == "__main__":
    main()