# -*- coding: utf-8 -*-
"""v2.1 M5: SQLite → PostgreSQL+pgvector 一次性迁移。

策略：
- 用 SqliteBackend 读、PostgresBackend 写；两者接口一致（BaseBackend）。
- 表顺序：resumes → jds → knowledge_chunks → match_history → optimizations → quality_checks
  （依赖 FK：chunks 依赖 jds；optimizations 依赖 chunks；match 依赖 resumes+jds）
- knowledge_chunks 在迁移过程中重新跑 Embedder 生成 512 维 BGE 向量（旧库全为 NULL）
  原因：① sqlite 旧库 0/45 有向量；② 真模型语义质量远胜 mock。
- 默认 dry-run；--apply 才真正写入。
- 迁移完成后 sqlite 文件不删，由用户决定是否重命名 .backup。

使用：
    python scripts/migrate_sqlite_to_pg.py            # 预览
    python scripts/migrate_sqlite_to_pg.py --apply    # 实际跑
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from loguru import logger


# 迁移顺序：依赖前置先迁
TABLE_ORDER = ["resumes", "jds", "knowledge_chunks", "match_history",
               "optimizations", "quality_checks"]


def _open_sources(sqlite_path: str, pg_url: str):
    from database.backends.sqlite_backend import SqliteBackend
    from database.backends.postgres_backend import PostgresBackend
    src = SqliteBackend(db_path=sqlite_path)
    dst = PostgresBackend(pg_url)
    return src, dst


def _read_all_resumes(src):
    return src.list_resumes(user_id="__all__") if False else _read_all(src, "resumes")


def _read_all(src, table: str):
    """直接走 sqlite 原生连接，包括软删行（deleted_at 字段透传给 PG）。"""
    import sqlite3
    conn = sqlite3.connect(src.db_path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(f"SELECT * FROM {table}").fetchall()]
    conn.close()
    return rows


def _reembed_chunks(rows):
    """对 knowledge_chunks 重新跑 BGE；保留旧 chunk_text 与元数据。"""
    from tools.embedder import Embedder
    emb = Embedder()
    texts = [r["chunk_text"] for r in rows]
    vectors = emb.embed_batch(texts) if texts else []
    out = []
    for r, vec in zip(rows, vectors):
        r = dict(r)
        r["embedding"] = vec
        r["embedding_dim"] = len(vec)
        out.append(r)
    logger.info(f"  reembedded {len(out)} chunks (dim={emb.dim})")
    return out


def _migrate_resumes(dst, rows):
    n = 0
    for r in rows:
        # JsonB fields：sqlite 侧存为 JSON 字符串，PG backend 接收后自动按 str 处理
        dst.insert_resume({
            "id": r["id"], "user_id": r["user_id"], "name": r["name"],
            "phone": r.get("phone"), "email": r.get("email"),
            "summary": r.get("summary"),
            "skills": _safe_json(r.get("skills")),
            "experience_years": r.get("experience_years", 0),
            "domains": _safe_json(r.get("domains")),
            "target_roles": _safe_json(r.get("target_roles")),
            "preferred_locations": _safe_json(r.get("preferred_locations")),
            "education": _safe_json(r.get("education")),
            "projects": _safe_json(r.get("projects")),
        })
        n += 1
    return n


def _migrate_jds(dst, rows):
    n = 0
    for r in rows:
        dst.insert_jd({
            "id": r["id"], "user_id": r["user_id"], "url": r.get("url", ""),
            "title": r.get("title", ""), "company": r.get("company", ""),
            "location": r.get("location", ""),
            "salary_str": r.get("salary_str"),
            "salary_min": r.get("salary_min"), "salary_max": r.get("salary_max"),
            "requirements": _safe_json(r.get("requirements")),
            "preferred_requirements": _safe_json(r.get("preferred_requirements")),
            "skills_required": _safe_json(r.get("skills_required")),
            "implicit_requirements": r.get("implicit_requirements"),
            "raw_text": r.get("raw_text", ""),
            "parsed_data": _safe_json(r.get("parsed_data")),
            "source": r.get("source", "manual"),
            "search_keyword": r.get("search_keyword"),
            "platform": r.get("platform"),
            "job_id": r.get("job_id"),
            "language": r.get("language", "zh"),
            "industry_tag": r.get("industry_tag"),
            "function_tag": r.get("function_tag"),
            "position_tag": r.get("position_tag"),
            "auto_classified": r.get("auto_classified", 1),
            "is_public": r.get("is_public", 0),
            "crawled_at": r.get("crawled_at"),
        })
        n += 1
    return n


def _migrate_chunks(dst, rows):
    """chunks 已在 _reembed_chunks 中被注入 embedding；逐条 insert_chunk。"""
    n = 0
    for r in rows:
        dst.insert_chunk({
            "id": r["id"], "user_id": r["user_id"], "jd_id": r["jd_id"],
            "chunk_index": r.get("chunk_index", n),
            "chunk_text": r.get("chunk_text", ""),
            "chunk_type": r.get("chunk_type", "full"),
            "keywords": _safe_json(r.get("keywords")),
            "embedding": r.get("embedding"),
            "embedding_dim": r.get("embedding_dim"),
            "context": r.get("context", ""),
            "heading_path": _safe_json(r.get("heading_path")),
        })
        n += 1
    return n


def _migrate_matches(dst, rows):
    n = 0
    for r in rows:
        dst.insert_match({
            "id": r["id"], "user_id": r["user_id"],
            "resume_id": r["resume_id"], "jd_id": r["jd_id"],
            "score": r["score"], "reasoning": r.get("reasoning", ""),
            "matched_skills": _safe_json(r.get("matched_skills")),
            "missing_skills": _safe_json(r.get("missing_skills")),
            "gaps": _safe_json(r.get("gaps")),
            "recommendations": _safe_json(r.get("recommendations")),
            "skill_mapping": _safe_json(r.get("skill_mapping")),
            "should_apply": r.get("should_apply", 0),
            "user_feedback": r.get("user_feedback"),
            "applied": r.get("applied", 0), "applied_at": r.get("applied_at"),
        })
        n += 1
    return n


def _migrate_opts(dst, rows):
    n = 0
    for r in rows:
        dst.insert_optimization({
            "id": r["id"], "user_id": r["user_id"],
            "resume_id": r.get("resume_id"), "jd_id": r["jd_id"],
            "chunk_id": r.get("chunk_id"),
            "optimization_type": r.get("optimization_type", "modify"),
            "section": r.get("section"),
            "original_content": r.get("original_content"),
            "suggested_content": r.get("suggested_content"),
            "reason": r.get("reason", ""),
            "user_adopted": r.get("user_adopted", 0),
            "user_rating": r.get("user_rating"),
        })
        n += 1
    return n


def _migrate_qc(dst, rows):
    n = 0
    for r in rows:
        dst.insert_quality_check({
            "check_type": r["check_type"],
            "target_table": r.get("target_table"),
            "target_id": r.get("target_id"),
            "score": r.get("score"),
            "details": _safe_json(r.get("details")),
            "user_id": r.get("user_id", "default"),
        })
        n += 1
    return n


def _safe_json(v):
    """sqlite 里 JSON 列存的是字符串或 None；统一转回 Python 对象供 backend 再序列化。"""
    import json
    if v is None:
        return [] if not isinstance(v, dict) else v
    if isinstance(v, (list, dict)):
        return v
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (json.JSONDecodeError, ValueError):
            return v
    return v


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite", default=str(PROJECT_ROOT / "data" / "jobhunter_v2.db"))
    parser.add_argument("--pg-url",
                        default=os.environ.get("DATABASE_URL",
                            "postgresql://jobhunter:jobhunter@localhost:5432/jobhunter"))
    parser.add_argument("--apply", action="store_true",
                        help="默认 dry-run；带此 flag 才实际写入")
    args = parser.parse_args()

    logger.info(f"Source SQLite: {args.sqlite}")
    logger.info(f"Target PG:     {args.pg_url}")
    logger.info(f"Mode: {'APPLY' if args.apply else 'DRY-RUN'}")

    src, dst = _open_sources(args.sqlite, args.pg_url)

    summary = {}
    for table in TABLE_ORDER:
        rows = _read_all(src, table)
        summary[table] = len(rows)
        logger.info(f"[{table}] read {len(rows)} rows from sqlite")

        if not args.apply:
            continue

        if table == "resumes":
            n = _migrate_resumes(dst, rows)
        elif table == "jds":
            n = _migrate_jds(dst, rows)
        elif table == "knowledge_chunks":
            reembedded = _reembed_chunks(rows)
            n = _migrate_chunks(dst, reembedded)
        elif table == "match_history":
            n = _migrate_matches(dst, rows)
        elif table == "optimizations":
            n = _migrate_opts(dst, rows)
        elif table == "quality_checks":
            n = _migrate_qc(dst, rows)
        else:
            continue
        logger.info(f"  → wrote {n} rows to PG")

    logger.info("=" * 50)
    logger.info("Migration summary:")
    for k, v in summary.items():
        logger.info(f"  {k:25s} {v}")
    if not args.apply:
        logger.info("DRY-RUN only. Re-run with --apply to actually write.")
    else:
        logger.info("Done. Verify with: docker compose exec postgres psql -U jobhunter -d jobhunter -c "
                    "\"SELECT chunk_type, COUNT(*) FROM knowledge_chunks GROUP BY chunk_type;\"")


if __name__ == "__main__":
    main()
