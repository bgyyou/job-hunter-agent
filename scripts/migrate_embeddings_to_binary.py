"""Populate sqlite-vec vec0 index + (optional) rewrite knowledge_chunks.embedding from JSON to float32 binary BLOB.

v4 P0-模块 3 实施脚本：把现有 24k+ chunks 从 JSON.dumps list 改成 float32 binary BLOB 写到 knowledge_chunks.embedding，
并同步 INSERT 到 vec0 虚拟表 knowledge_chunks_vec（distance_metric=cosine），让 vector_search 能走 vec0 fast-path。

设计要点：
- 必须 512 维（BGE-small-zh-v1.5）；其他维度的 chunk 跳过 vec0（vector_search 走 numpy fallback）
- 幂等：vec0 表里已有 rowid 的 INSERT OR REPLACE；embedding 列 if rewrite_blob 二次写入也是 UPDATE 安全
- --rollback 把 vec0 清空（不重写 embedding 回 JSON，因为 CLAUDE.md "不做向后兼容 hack"）
  但回滚只清 vec0，恢复后 vector_search 自动落到 numpy fallback（json 读取兼容代码保留）
- --dry-run 只统计不写

Usage:
    python scripts/migrate_embeddings_to_binary.py                    # populate + rewrite
    python scripts/migrate_embeddings_to_binary.py --dry-run         # report only
    python scripts/migrate_embeddings_to_binary.py --no-rewrite-blob  # populate vec0 only，保留 JSON embedding 列
    python scripts/migrate_embeddings_to_binary.py --rollback        # 清空 vec0
    python scripts/migrate_embeddings_to_binary.py --batch-size 500
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from loguru import logger  # noqa: E402

VEC0_TABLE = "knowledge_chunks_vec"
BGE_DIM = 512


def _connect_with_vec0(db_path: str) -> sqlite3.Connection:
    """打开 DB 并加载 sqlite-vec 扩展，vec0 虚拟表才能 INSERT。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # 让 rows[rowid] 这种属性访问可用
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.enable_load_extension(True)
    try:
        import sqlite_vec
        sqlite_vec.load(conn)
        logger.info("sqlite-vec loaded (vec0 enabled)")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"sqlite-vec load failed: {exc}")
        raise SystemExit(1)
    finally:
        conn.enable_load_extension(False)
    return conn


def _decode_embedding(blob) -> "list[float] | None":
    """复用 SqliteBackend._blob_to_embedding 的语义（json + float32 binary 兼容）。"""
    if blob is None:
        return None
    if isinstance(blob, list):
        return blob
    raw = bytes(blob) if isinstance(blob, (bytes, bytearray)) else (
        blob.encode("utf-8") if isinstance(blob, str) else None
    )
    if raw is None:
        return None
    n = len(raw)
    if n > 0 and n % 4 == 0:
        try:
            import numpy as np
            arr = np.frombuffer(raw, dtype=np.float32)
            if arr.size > 0 and np.all(np.isfinite(arr)):
                return arr.tolist()
        except (ValueError, TypeError):
            pass
    try:
        import json
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _serialize_float32(vec: list[float]) -> bytes:
    """list[float] → numpy float32 LE bytes（直接 tobytes，与 SqliteBackend._embedding_to_blob 一致）。"""
    import numpy as np
    return np.asarray(vec, dtype=np.float32).tobytes()


def rollback_vec0(conn: sqlite3.Connection) -> int:
    """DELETE FROM knowledge_chunks_vec；返回受影响行数。"""
    cur = conn.execute(f"DELETE FROM {VEC0_TABLE} WHERE 1=1")
    conn.commit()
    deleted = cur.rowcount
    logger.info(f"rollback: cleared {deleted} rows from {VEC0_TABLE}")
    return deleted


def migrate(
    db_path: str,
    *,
    dry_run: bool = False,
    rewrite_blob: bool = True,
    batch_size: int = 1000,
) -> dict:
    """Populate vec0 + (optional) rewrite knowledge_chunks.embedding to float32 binary.

    Returns dict with: n_total / n_written_vec0 / n_skipped_dim / n_rewritten_blob / vec0_total / elapsed_sec.
    """
    import numpy as np

    conn = _connect_with_vec0(db_path)

    # 0) 防御：vec0 表不存在就退出（要求先跑 014 migration）
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (VEC0_TABLE,)
    ).fetchone()
    if not row:
        logger.error(f"{VEC0_TABLE} not exists. Run app once to trigger migration 014 first.")
        conn.close()
        raise SystemExit(1)

    vec0_before = conn.execute(f"SELECT COUNT(*) FROM {VEC0_TABLE}").fetchone()[0]
    chunks_total = conn.execute(
        "SELECT COUNT(*) FROM knowledge_chunks WHERE deleted_at IS NULL AND embedding IS NOT NULL"
    ).fetchone()[0]
    logger.info(f"stats before: knowledge_chunks active={chunks_total} vec0_indexed={vec0_before}")

    if dry_run:
        logger.info("[DRY RUN] would iterate over {} chunks, no writes".format(chunks_total))
        conn.close()
        return {
            "n_total": chunks_total,
            "vec0_before": vec0_before,
            "dry_run": True,
        }

    # 1) 流式读 + 处理
    rows = conn.execute(
        "SELECT rowid, embedding, embedding_dim FROM knowledge_chunks "
        "WHERE deleted_at IS NULL AND embedding IS NOT NULL"
    )

    n_total = 0
    n_written_vec0 = 0
    n_skipped_dim = 0
    n_skipped_decode = 0
    n_rewritten_blob = 0

    vec0_buffer: list[tuple[int, bytes]] = []

    start = time.time()
    for row in rows:
        n_total += 1
        rowid = int(row["rowid"])
        emb_dim = row["embedding_dim"]
        vec = _decode_embedding(row["embedding"])
        if vec is None:
            n_skipped_decode += 1
            continue
        if emb_dim is None or emb_dim != BGE_DIM or len(vec) != BGE_DIM:
            n_skipped_dim += 1
            continue

        new_blob = _serialize_float32(vec)
        vec0_buffer.append((rowid, new_blob))
        if rewrite_blob:
            conn.execute(
                "UPDATE knowledge_chunks SET embedding = ?, embedding_dim = ? WHERE rowid = ?",
                (new_blob, BGE_DIM, rowid),
            )
            n_rewritten_blob += 1

        # 每 batch_size 行 flush vec0 + commit
        if len(vec0_buffer) >= batch_size:
            conn.executemany(
                f"INSERT OR REPLACE INTO {VEC0_TABLE}(rowid, embedding) VALUES (?, ?)",
                vec0_buffer,
            )
            n_written_vec0 += len(vec0_buffer)
            vec0_buffer.clear()
            conn.commit()
            if n_total % (batch_size * 5) == 0:
                logger.info(
                    f"  progress: {n_total}/{chunks_total} processed "
                    f"({n_written_vec0} vec0 written, {n_rewritten_blob} blob rewritten)"
                )

    # 2) flush 尾巴
    if vec0_buffer:
        conn.executemany(
            f"INSERT OR REPLACE INTO {VEC0_TABLE}(rowid, embedding) VALUES (?, ?)",
            vec0_buffer,
        )
        n_written_vec0 += len(vec0_buffer)
        vec0_buffer.clear()

    # 3) 收紧 WAL + commit
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    vec0_after = conn.execute(f"SELECT COUNT(*) FROM {VEC0_TABLE}").fetchone()[0]
    elapsed = time.time() - start
    conn.close()

    logger.info(
        f"DONE: total={n_total} vec0_written={n_written_vec0} "
        f"blob_rewritten={n_rewritten_blob} skipped_dim={n_skipped_dim} "
        f"skipped_decode={n_skipped_decode} vec0_total_now={vec0_after} "
        f"elapsed={elapsed:.1f}s"
    )

    return {
        "n_total": n_total,
        "n_written_vec0": n_written_vec0,
        "n_rewritten_blob": n_rewritten_blob,
        "n_skipped_dim": n_skipped_dim,
        "n_skipped_decode": n_skipped_decode,
        "vec0_after": vec0_after,
        "elapsed_sec": round(elapsed, 1),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        default="data/jobhunter_v2.db",
        help="SQLite DB 路径（默认 data/jobhunter_v2.db）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只统计，不写")
    parser.add_argument(
        "--no-rewrite-blob",
        action="store_true",
        help="只 populate vec0，不重写 knowledge_chunks.embedding 列（保留 JSON 老格式）",
    )
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="清空 knowledge_chunks_vec（vector_search 自动回退 numpy path）",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="每 N 行 commit 一次（默认 1000）",
    )
    args = parser.parse_args()

    db_path = args.db
    if not Path(db_path).exists():
        logger.error(f"DB not found: {db_path}")
        raise SystemExit(1)

    if args.rollback:
        conn = _connect_with_vec0(db_path)
        rollback_vec0(conn)
        conn.close()
        return

    migrate(
        db_path,
        dry_run=args.dry_run,
        rewrite_blob=not args.no_rewrite_blob,
        batch_size=args.batch_size,
    )


if __name__ == "__main__":
    main()
