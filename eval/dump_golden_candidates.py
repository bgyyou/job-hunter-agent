"""Golden 校准集 dump 脚本 (P0-模块 6 子任务 2)

输入：
- eval/baseline_50_queries.jsonl — 50 条 query（含 origin_jd_id, origin_source, origin_title）
- eval/baseline_50_results.jsonl — 15 条有 LLM judge 评分的 query（含 top-10 recalled_jd_ids + llm_score）
- data/jobhunter_v2.db — 真实 chunk_text / jd_titles（拿 jd_snippet）

输出：
- eval/golden_candidates.jsonl — 50 条待标 query + candidates（jd_id, jd_title, jd_snippet, llm_judge_score, human_score=None）

设计：
- 50 条 query 全量 dump
- candidate 来源：优先用 baseline_50_results.jsonl 的 top-10（已被 LLM judge 评过）
  + origin_jd（query 自身的 JD）作为必加 ground truth
- human_score 字段 = None，用户明天标
- 缺 baseline_50_results.jsonl 评分的 query 仍 dump，candidate 仅用 origin_jd + 随机几个 top-10

跑法：python eval/dump_golden_candidates.py
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_queries(path: Path) -> Dict[str, Dict[str, Any]]:
    """读 baseline_50_queries.jsonl → {query_id: query_record}"""
    out = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            out[r["query_id"]] = r
    return out


def load_results(path: Path) -> Dict[str, Dict[str, Any]]:
    """读 baseline_50_results.jsonl → {query_id: result_record}"""
    out = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            out[r["query_id"]] = r
    return out


def load_jd_index(db_path: Path) -> Dict[str, Dict[str, Any]]:
    """读 DB → {jd_id: {title, raw_text, industry, position, source}}"""
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT id, title, source, raw_text, industry_tag, position_tag FROM jds"
    ).fetchall()
    out = {}
    for jd_id, title, source, raw_text, industry, position in rows:
        out[jd_id] = {
            "title": title or "",
            "source": source,
            "raw_text": (raw_text or "")[:300],
            "industry": industry or "",
            "position": position or "",
        }
    conn.close()
    return out


MIN_CANDIDATES = 5  # 每条 query 至少要有几个 candidates（不够时从同 source 抽干扰）


def build_candidates(
    query_id: str,
    query_rec: Dict[str, Any],
    result_rec: Optional[Dict[str, Any]],
    jd_index: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """构造一条 query 的 candidate 列表。

    顺序：
    1. origin_jd（query 自己的 JD，必加 ground truth；找不到时用 placeholder）
    2. baseline_50_results.jsonl 里的 top-10（按 recalled_jd_ids 顺序）
    3. 兜底：从同 source 的 jd_index 随机抽 4 个干扰 JD，补到 ≥MIN_CANDIDATES
    """
    import random
    candidates = []
    seen_ids = set()

    # 1. origin_jd（必加）
    origin_id = query_rec.get("origin_jd_id")
    origin_title = query_rec.get("origin_title", "")
    origin_source = query_rec.get("origin_source", "")
    if origin_id:
        jd = jd_index.get(origin_id, {})
        title = jd.get("title", "") or origin_title
        snippet = jd.get("raw_text", "")[:200] if jd else ""
        candidates.append(
            {
                "jd_id": origin_id,
                "jd_title": title,
                "jd_snippet": snippet,
                "llm_judge_score": None,
                "is_origin_jd": True,
                "human_score": None,
            }
        )
        seen_ids.add(origin_id)
    elif origin_title:
        # origin_jd_id 找不到时仍占位（保留 origin_title 供人判断）
        candidates.append(
            {
                "jd_id": f"ORIGIN_NOT_FOUND:{origin_id}",
                "jd_title": origin_title,
                "jd_snippet": "",
                "llm_judge_score": None,
                "is_origin_jd": True,
                "human_score": None,
            }
        )

    # 2. recalled top-10
    if result_rec:
        recalled_ids = result_rec.get("recalled_jd_ids", [])
        scores = result_rec.get("scores", [])
        for i, jd_id in enumerate(recalled_ids[:10]):
            if jd_id in seen_ids:
                continue
            seen_ids.add(jd_id)
            jd = jd_index.get(jd_id, {})
            llm_score = scores[i] if i < len(scores) else None
            candidates.append(
                {
                    "jd_id": jd_id,
                    "jd_title": jd.get("title", ""),
                    "jd_snippet": jd.get("raw_text", "")[:200],
                    "llm_judge_score": llm_score,
                    "is_origin_jd": False,
                    "human_score": None,
                }
            )

    # 3. 兜底：候选数 < MIN_CANDIDATES 时从同 source 抽干扰 JD
    if len(candidates) < MIN_CANDIDATES:
        pool = [
            (jid, jd) for jid, jd in jd_index.items()
            if jid not in seen_ids
            and (not origin_source or jd.get("source") == origin_source)
        ]
        random.seed(hash(query_id) & 0xFFFFFFFF)  # 确定性，便于复现
        random.shuffle(pool)
        for jid, jd in pool[: MIN_CANDIDATES - len(candidates)]:
            candidates.append(
                {
                    "jd_id": jid,
                    "jd_title": jd.get("title", ""),
                    "jd_snippet": jd.get("raw_text", "")[:200],
                    "llm_judge_score": None,
                    "is_origin_jd": False,
                    "human_score": None,
                    "is_distractor": True,
                }
            )

    return candidates


def main():
    queries_path = PROJECT_ROOT / "eval" / "baseline_50_queries.jsonl"
    results_path = PROJECT_ROOT / "eval" / "baseline_50_results.jsonl"
    db_path = PROJECT_ROOT / "data" / "jobhunter_v2.db"
    output_path = PROJECT_ROOT / "eval" / "golden_candidates.jsonl"

    print(f"[INFO] 加载 queries: {queries_path}")
    queries = load_queries(queries_path)
    print(f"[INFO] 加载 {len(queries)} 条 query")

    print(f"[INFO] 加载 results: {results_path}")
    results = load_results(results_path)
    print(f"[INFO] 加载 {len(results)} 条有 LLM 评分的结果")

    print(f"[INFO] 加载 DB jd index: {db_path}")
    jd_index = load_jd_index(db_path)
    print(f"[INFO] 加载 {len(jd_index)} 条 JD")

    print(f"[INFO] 构造 candidates → {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    n_with_origin = 0
    n_with_top10 = 0
    n_total_candidates = 0

    with output_path.open("w", encoding="utf-8") as f:
        for qid in sorted(queries.keys()):
            q = queries[qid]
            r = results.get(qid)
            cands = build_candidates(qid, q, r, jd_index)
            if not cands:
                continue
            if any(c["is_origin_jd"] for c in cands):
                n_with_origin += 1
            if r and r.get("recalled_jd_ids"):
                n_with_top10 += 1
            n_total_candidates += len(cands)

            record = {
                "query_id": qid,
                "query": q["query"],
                "query_source": q.get("origin_source", "unknown"),
                "query_form": q.get("form", "unknown"),
                "query_type": q.get("query_type", "unknown"),
                "origin_title": q.get("origin_title", ""),
                "origin_jd_id": q.get("origin_jd_id", ""),
                "llm_n_relevant_in_top10": (r.get("n_relevant_in_top_k") if r else None),
                "candidates": cands,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"[OK] 输出 {len(queries)} 条 query")
    print(f"     含 origin_jd（ground truth）: {n_with_origin}")
    print(f"     含 LLM-judged top-10: {n_with_top10}")
    print(f"     总 candidate 数: {n_total_candidates}")
    print(f"     平均每 query candidate: {n_total_candidates / len(queries):.1f}")


if __name__ == "__main__":
    main()