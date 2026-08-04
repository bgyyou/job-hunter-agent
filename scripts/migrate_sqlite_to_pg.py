# -*- coding: utf-8 -*-
"""SQLite → PostgreSQL+pgvector 一次性迁移。

策略（M-v4-2 / P1-012 重写）：
- **通用列拷贝**：每张表读 sqlite 的 PRAGMA 列 + PG 的 information_schema 列，
  取交集后拼参数化 INSERT。schema 加字段自动跟随，不再有手写列白名单。
  上一版为每张表手写 _migrate_*() 枚举列，已对着 004 收敛前的旧 schema 漂移：
  往 jds 写 requirements/skills_required/parsed_data（列已不存在），
  同时丢掉 parsed_sections/tags/quality_score/deleted_at（列实际存在）。
- **类型转换由 PG 的 udt_name 驱动**：jsonb → %s::jsonb，vector → %s::vector，
  text[] → Python list，其余原样。不硬编码任何列名。
- **user_id 保留源值**：sqlite 行已带真实归属（v4 多用户）。--user-id 只作为
  user_id 为空的历史行的兜底，不覆盖已有归属，否则多租户会被塌成单用户。
- knowledge_chunks 迁移时重跑 Embedder 生成向量（sqlite 侧 embedding 是
  sqlite-vec 的二进制格式，与 pgvector 不通用，只能重算）。
- 表顺序按 FK 依赖排；ON CONFLICT DO NOTHING 保证重跑幂等。
- 默认 dry-run；--apply 才真正写入。dry-run 也连 PG，用于提前报告列差异。
- 迁移完成后 sqlite 文件不删，由用户决定是否重命名 .backup。

使用：
    python scripts/migrate_sqlite_to_pg.py --user-id <fallback_owner>          # 预览
    python scripts/migrate_sqlite_to_pg.py --user-id <fallback_owner> --apply  # 实际跑
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from loguru import logger


# 迁移顺序：FK 依赖前置先迁（users 最先，无依赖的工具表最后）
TABLE_ORDER = [
    "users",
    "resumes",
    "jds",
    "jd_structured",
    "knowledge_chunks",
    "match_history",
    "optimizations",
    "quality_checks",
    "flow_a_drafts",
    "rewrite_history",
    "interview_questions",
    "llm_calls",
    "audit_logs",
    "skeleton_cache",
]

# 不迁移：sqlite 内部表、迁移元数据、sqlite-vec 虚拟表的影子表
# （向量在 PG 侧由 pgvector 承载，chunks 迁移时重算，影子表无意义）
SKIP_TABLES = {"sqlite_sequence", "schema_version"}
SKIP_PREFIXES = ("knowledge_chunks_vec",)

BATCH_SIZE = 500


def _sqlite_columns(sqlite_path: str, table: str) -> List[str]:
    conn = sqlite3.connect(sqlite_path)
    try:
        return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    finally:
        conn.close()


def _pg_columns(pg_conn, table: str) -> Dict[str, str]:
    """返回 {column_name: udt_name}；表不存在时返回空 dict。"""
    with pg_conn.cursor() as cur:
        cur.execute(
            """SELECT column_name, udt_name
               FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = %s""",
            (table,),
        )
        return {r[0]: r[1] for r in cur.fetchall()}


def _read_all(sqlite_path: str, table: str) -> List[Dict[str, Any]]:
    """走 sqlite 原生连接读全表，包括软删行（deleted_at 透传给 PG）。"""
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(f"SELECT * FROM {table}")]
    finally:
        conn.close()


def _placeholder(udt: str) -> str:
    """按 PG 列类型决定占位符的 cast —— sqlite 侧一律是 TEXT，需显式转。"""
    if udt in ("jsonb", "json"):
        return f"%s::{udt}"
    if udt == "vector":
        return "%s::vector"
    return "%s"


def _coerce(value: Any, udt: str) -> Any:
    """把 sqlite 的值转成 PG 该列能接受的形态。"""
    if value is None:
        return None

    if udt in ("jsonb", "json"):
        # sqlite 存的是 JSON 字符串；非法 JSON 兜底包成 JSON 字符串，不让整批挂掉
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        if isinstance(value, str):
            try:
                json.loads(value)
                return value
            except (json.JSONDecodeError, ValueError):
                return json.dumps(value, ensure_ascii=False)
        return json.dumps(value, ensure_ascii=False)

    if udt.startswith("_"):  # PG 数组类型，如 _text
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, list) else [value]
            except (json.JSONDecodeError, ValueError):
                return [value]
        return [value]

    if udt == "bool" and isinstance(value, int):
        return bool(value)

    return value


def _reembed_chunks(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """sqlite 的 embedding 是 sqlite-vec 二进制，与 pgvector 不通用 → 重算。"""
    from tools.embedder import Embedder

    emb = Embedder()
    texts = [r.get("chunk_text") or "" for r in rows]
    vectors = emb.embed_batch(texts) if texts else []
    out = []
    for r, vec in zip(rows, vectors):
        r = dict(r)
        r["embedding"] = "[" + ",".join(f"{v:.7f}" for v in vec) + "]"
        r["embedding_dim"] = len(vec)
        out.append(r)
    logger.info(f"  reembedded {len(out)} chunks (dim={emb.dim})")
    return out


def _copy_table(pg_conn, table: str, rows: List[Dict[str, Any]],
                sqlite_cols: List[str], pg_cols: Dict[str, str],
                fallback_user_id: str) -> int:
    """按列交集拷贝一张表。返回写入行数。"""
    from psycopg2.extras import execute_batch

    cols = [c for c in sqlite_cols if c in pg_cols]
    if not cols:
        logger.warning(f"  [{table}] no overlapping columns, skipped")
        return 0

    dropped = [c for c in sqlite_cols if c not in pg_cols]
    if dropped:
        logger.warning(f"  [{table}] sqlite-only columns dropped: {dropped}")
    missing = [c for c in pg_cols if c not in sqlite_cols]
    if missing:
        logger.info(f"  [{table}] PG-only columns left at default: {missing}")

    placeholders = ", ".join(_placeholder(pg_cols[c]) for c in cols)
    sql = (f'INSERT INTO {table} ({", ".join(cols)}) VALUES ({placeholders}) '
           f"ON CONFLICT DO NOTHING")

    params = []
    for r in rows:
        # user_id 保留源值；只有空值才落到 fallback，避免多租户被塌成单用户
        if "user_id" in cols and not r.get("user_id"):
            r = dict(r, user_id=fallback_user_id)
        params.append(tuple(_coerce(r.get(c), pg_cols[c]) for c in cols))

    with pg_conn.cursor() as cur:
        execute_batch(cur, sql, params, page_size=BATCH_SIZE)
    return len(params)


def _resync_sequences(pg_conn, table: str) -> None:
    """显式带 id 拷贝后，serial 序列还停在 1，后续 INSERT 会撞 PK。"""
    with pg_conn.cursor() as cur:
        cur.execute(
            """SELECT column_name FROM information_schema.columns
               WHERE table_schema='public' AND table_name=%s
                 AND column_default LIKE 'nextval%%'""",
            (table,),
        )
        for (col,) in cur.fetchall():
            cur.execute(
                f"SELECT setval(pg_get_serial_sequence(%s, %s), "
                f"COALESCE((SELECT MAX({col}) FROM {table}), 1))",
                (table, col),
            )
            logger.debug(f"  [{table}] sequence for {col} resynced")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite", default=str(PROJECT_ROOT / "data" / "jobhunter_v2.db"))
    parser.add_argument("--pg-url",
                        default=os.environ.get("DATABASE_URL",
                            "postgresql://jobhunter:jobhunter@localhost:5432/jobhunter"))
    parser.add_argument("--apply", action="store_true",
                        help="默认 dry-run；带此 flag 才实际写入")
    parser.add_argument("--user-id", required=True,
                        help="user_id 为空的历史行的兜底归属（不覆盖已有 user_id）")
    parser.add_argument("--rollback-on-fail", dest="rollback_on_fail",
                        action=argparse.BooleanOptionalAction, default=True,
                        help="迁移任一张表失败时自动 rollback 整个事务（默认 True；"
                             "传 --no-rollback-on-fail 关闭）")
    args = parser.parse_args()

    logger.info(f"Source SQLite: {args.sqlite}")
    logger.info(f"Target PG:     {args.pg_url}")
    logger.info(f"Mode: {'APPLY' if args.apply else 'DRY-RUN'}")
    logger.info(f"Rollback-on-fail: {args.rollback_on_fail}")

    import psycopg2

    pg_conn = psycopg2.connect(args.pg_url)
    pg_conn.autocommit = False

    summary: Dict[str, str] = {}
    failed_table: Optional[str] = None
    try:
        for table in TABLE_ORDER:
            if table in SKIP_TABLES or table.startswith(SKIP_PREFIXES):
                continue

            sqlite_cols = _sqlite_columns(args.sqlite, table)
            if not sqlite_cols:
                logger.warning(f"[{table}] not present in sqlite, skipped")
                summary[table] = "absent in sqlite"
                continue

            pg_cols = _pg_columns(pg_conn, table)
            if not pg_cols:
                logger.error(f"[{table}] not present in PG — run migrations_pg first")
                summary[table] = "MISSING IN PG"
                continue

            rows = _read_all(args.sqlite, table)
            logger.info(f"[{table}] read {len(rows)} rows from sqlite")

            if not args.apply:
                dropped = [c for c in sqlite_cols if c not in pg_cols]
                summary[table] = f"{len(rows)} rows" + (f" (would drop {dropped})" if dropped else "")
                continue

            if table == "knowledge_chunks":
                rows = _reembed_chunks(rows)

            n = _copy_table(pg_conn, table, rows, sqlite_cols, pg_cols, args.user_id)
            _resync_sequences(pg_conn, table)
            pg_conn.commit()
            logger.info(f"  → wrote {n} rows to PG")
            summary[table] = f"{n} rows"
    except Exception as exc:
        failed_table = table if "table" in locals() else None
        if args.rollback_on_fail:
            try:
                pg_conn.rollback()
                logger.error(
                    f"迁移失败：表 {failed_table or '?'} 异常 {type(exc).__name__}: {exc}；"
                    f"已 rollback，PG 侧不会留半成品数据。"
                )
            except Exception as rb_exc:  # noqa: BLE001
                logger.error(f"rollback 自身失败：{rb_exc}")
        else:
            logger.error(
                f"迁移失败：表 {failed_table or '?'} 异常 {type(exc).__name__}: {exc}；"
                f"--no-rollback-on-fail 已传，PG 侧可能留半成品事务，需手动清理。"
            )
        raise
    finally:
        pg_conn.close()

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
