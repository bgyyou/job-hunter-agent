"""Backfill legacy chunk_type='full' chunks.

Reads every knowledge_chunks row where chunk_type='full' AND legacy=0,
re-splits the text with SemanticChunker, re-embeds with the BGE Embedder,
inserts the new chunks (under the same jd_id), then marks the old rows
legacy=1 (kept for audit, excluded from search via legacy=1 filter).

Idempotent: re-running won't reprocess rows already marked legacy=1.

Usage:
    python scripts/backfill_chunks.py            # run for real
    python scripts/backfill_chunks.py --dry-run  # report only
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from loguru import logger  # noqa: E402

from tools.chunker import SemanticChunker  # noqa: E402
from tools.embedder import Embedder  # noqa: E402
from database.backends.sqlite_backend import SqliteBackend  # noqa: E402


def _embedding_to_blob(vec):
    import json
    return json.dumps(list(vec)).encode("utf-8") if vec is not None else None


def backfill(db_path: str, dry_run: bool = False) -> dict:
    backend = SqliteBackend(db_path=db_path)  # ensures legacy column migration
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, jd_id, chunk_text, user_id FROM knowledge_chunks "
        "WHERE chunk_type='full' AND legacy=0 AND deleted_at IS NULL"
    ).fetchall()

    if not rows:
        logger.info("no legacy 'full' chunks to backfill")
        conn.close()
        return {"processed": 0, "new_chunks": 0, "marked_legacy": 0}

    chunker = SemanticChunker()
    embedder = Embedder()
    new_chunks = 0
    type_distribution: dict[str, int] = {}

    for row in rows:
        text = row["chunk_text"]
        jd_id = row["jd_id"]
        old_id = row["id"]
        user_id = row["user_id"] or "default"

        chunks = chunker.split(text)
        if not chunks:
            logger.warning(f"chunker returned 0 pieces for old chunk {old_id} (jd={jd_id}); skipping")
            continue

        # Find next chunk_index for this jd_id (avoid PK collision).
        max_idx = conn.execute(
            "SELECT COALESCE(MAX(chunk_index), -1) FROM knowledge_chunks WHERE jd_id=?",
            (jd_id,),
        ).fetchone()[0]
        next_idx = max_idx + 1

        # Embed all pieces in one batch.
        embeddings = embedder.embed_batch([c.chunk_text for c in chunks])

        if dry_run:
            logger.info(f"[dry-run] jd={jd_id}: would insert {len(chunks)} chunks "
                        f"({[c.chunk_type for c in chunks]}) and mark old {old_id} legacy=1")
            for c in chunks:
                type_distribution[c.chunk_type] = type_distribution.get(c.chunk_type, 0) + 1
            new_chunks += len(chunks)
            continue

        for c, vec in zip(chunks, embeddings):
            type_distribution[c.chunk_type] = type_distribution.get(c.chunk_type, 0) + 1
            conn.execute(
                """INSERT INTO knowledge_chunks
                   (id, user_id, jd_id, chunk_index, chunk_text, chunk_type,
                    keywords, embedding, embedding_dim, context, heading_path, legacy)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                (str(uuid.uuid4()), user_id, jd_id, next_idx, c.chunk_text,
                 c.chunk_type, "[]", _embedding_to_blob(vec), len(vec),
                 "", "[]" if not c.heading_path else
                 __import__("json").dumps(c.heading_path, ensure_ascii=False)),
            )
            next_idx += 1
            new_chunks += 1

        conn.execute("UPDATE knowledge_chunks SET legacy=1 WHERE id=?", (old_id,))

    if not dry_run:
        conn.commit()
    conn.close()

    summary = {
        "processed": len(rows),
        "new_chunks": new_chunks,
        "marked_legacy": 0 if dry_run else len(rows),
        "chunk_type_distribution": type_distribution,
        "dry_run": dry_run,
    }
    logger.info(f"backfill summary: {summary}")
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(ROOT / "data" / "jobhunter_v2.db"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    backfill(args.db, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
