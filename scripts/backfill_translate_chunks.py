#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回填翻译：把 knowledge_chunks 中 language IN ('en', 'mixed') 的 chunk 翻译成中文并 re-embed。

2026-07-25 用户决策（plan file Q1 衍生命题）：
- 99% 索引 chunks 来自 jobsdb (English source)
- 中文 query 命中英文 chunk cosine 错配（q0084 "招聘经理coe" → Personal Assistant）
- 选 A 方案：索引时翻译英文 chunk 为中文，统一进 BGE-small-zh 向量空间

实施细节：
- 每次 batch 50 chunks，并发 8 个 LLM 调用
- 长文本按段落切，每段独立翻译再拼回
- 翻译成功 → chunk_text 替换为中文，original_text 存原文，translated_at = now
- re-embed：BGE-small-zh 重 embed，更新 vec0 + knowledge_chunks.embedding
- 翻译失败 → 跳过（translated_at 留空，下次回填可重试）

成本估算：~21,179 chunks × ~180 tokens ≈ 3.8M tokens ≈ $2 one-time
时间估算：并发 8 + 3s/call → ~3.5h；并发 16 → ~1.7h

用法：
    python scripts/backfill_translate_chunks.py --batch-size 50 --concurrency 8
    python scripts/backfill_translate_chunks.py --dry-run   # 只统计不翻译
    python scripts/backfill_translate_chunks.py --limit 100 # 跑 100 条验证
"""
from __future__ import annotations

import argparse
import asyncio
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

from loguru import logger  # noqa: E402

from services.translation_service import ChunkTranslator, detect_language  # noqa: E402


BGE_DIM = 512
DEFAULT_BATCH = 50
DEFAULT_CONCURRENCY = 8


def _to_blob(vec) -> bytes:
    import numpy as np
    return np.asarray(vec, dtype=np.float32).tobytes()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class BackfillRunner:
    """单进程回填。SQLite WAL 模式下并发读，写要分批 commit。"""

    def __init__(self, db_path: str, batch_size: int, concurrency: int, dry_run: bool):
        self.db_path = db_path
        self.batch_size = batch_size
        self.concurrency = concurrency
        self.dry_run = dry_run
        self.translator = ChunkTranslator(concurrency=concurrency)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.enable_load_extension(True)
        import sqlite_vec
        sqlite_vec.load(c)
        c.enable_load_extension(False)
        return c

    def stats(self) -> Dict[str, int]:
        conn = self._conn()
        try:
            total = conn.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0]
            by_lang = {
                r["language"]: r["n"]
                for r in conn.execute(
                    "SELECT language, COUNT(*) AS n FROM knowledge_chunks GROUP BY language"
                )
            }
            untranslated = conn.execute(
                "SELECT COUNT(*) FROM knowledge_chunks "
                "WHERE language IN ('en', 'mixed') AND translated_at IS NULL"
            ).fetchone()[0]
            return {
                "total_chunks": total,
                "by_language": by_lang,
                "to_translate": untranslated,
            }
        finally:
            conn.close()

    async def run(self, limit: int = 0) -> None:
        if self.dry_run:
            self._print_stats()
            return

        # 1. 加载 embedder
        from tools.embedder import Embedder

        embedder = Embedder()

        # 2. 分批循环
        total_done = 0
        total_failed = 0
        t0 = time.time()
        while True:
            conn = self._conn()
            try:
                rows = conn.execute(
                    """SELECT id, chunk_text, language FROM knowledge_chunks
                       WHERE language IN ('en', 'mixed') AND translated_at IS NULL
                       ORDER BY id LIMIT ?""",
                    (self.batch_size,),
                ).fetchall()
            finally:
                conn.close()

            if not rows:
                break

            if limit and total_done + len(rows) > limit:
                rows = rows[: limit - total_done]
                if not rows:
                    break

            batch_t0 = time.time()
            chunk_ids = [r["id"] for r in rows]
            chunk_texts = [r["chunk_text"] for r in rows]
            languages = [r["language"] for r in rows]

            # 翻译
            logger.info(
                f"translating batch: {len(rows)} chunks "
                f"(done={total_done}, failed={total_failed}, "
                f"elapsed={time.time()-t0:.0f}s)"
            )

            def _on_done(idx, _translated):
                pass  # 占位，gather 已经返回

            results = await self.translator.translate_batch(chunk_texts, on_done=_on_done)
            # results[i] = (original, translated, error)

            # 3. re-embed & update
            new_texts: List[str] = []
            new_embs: List[Optional[bytes]] = []
            new_dims: List[int] = []
            for (orig, zh, err), lang in zip(results, languages):
                if zh is None:
                    new_texts.append(orig)  # 失败：保留原文
                    new_embs.append(None)
                    new_dims.append(0)
                    total_failed += 1
                    logger.warning(f"  translation failed: {err[:80] if err else 'None'}")
                else:
                    new_texts.append(zh)
                    new_embs.append(None)
                    new_dims.append(BGE_DIM)

            # batch embed（只对成功翻译的做）
            embed_idx = [i for i, (_, zh, _) in enumerate(results) if zh is not None]
            if embed_idx:
                texts_to_embed = [new_texts[i] for i in embed_idx]
                # Embedder.embed() 接受单字符串
                for ti in embed_idx:
                    try:
                        vec = embedder.embed(new_texts[ti])
                        new_embs[ti] = _to_blob(vec)
                    except Exception as exc:
                        logger.warning(f"  embed failed: {exc}")
                        new_embs[ti] = None
                        total_failed += 1

            # 4. 写回 DB
            self._write_batch(
                chunk_ids=chunk_ids,
                languages=languages,
                original_texts=[r[0] for r in results],
                new_texts=new_texts,
                emb_blobs=new_embs,
                emb_dims=new_dims,
            )
            total_done += len(rows)
            elapsed = time.time() - batch_t0
            rate = len(rows) / max(elapsed, 0.1)
            logger.success(
                f"  batch done: {len(rows)} chunks in {elapsed:.1f}s "
                f"({rate:.1f} chunks/s) — total done={total_done}, failed={total_failed}"
            )

            if limit and total_done >= limit:
                break

        logger.success(
            f"=== 回填完成 ===\n"
            f"  total done: {total_done}\n"
            f"  total failed: {total_failed}\n"
            f"  total elapsed: {time.time()-t0:.0f}s"
        )
        self._print_stats()

    def _write_batch(
        self,
        chunk_ids: List[str],
        languages: List[str],
        original_texts: List[Optional[str]],
        new_texts: List[str],
        emb_blobs: List[Optional[bytes]],
        emb_dims: List[int],
    ) -> None:
        conn = self._conn()
        try:
            written = 0
            for cid, lang, orig_text, new_text, blob, dim in zip(
                chunk_ids, languages, original_texts, new_texts, emb_blobs, emb_dims
            ):
                if blob is None:
                    continue
                # 先 SELECT 拿到 rowid（lastrowid 在 UPDATE 上不可靠）
                row = conn.execute(
                    "SELECT rowid FROM knowledge_chunks WHERE id = ?", (cid,)
                ).fetchone()
                if row is None:
                    logger.warning(f"  write skipped: id {cid[:20]} not found")
                    continue
                rowid = row[0]
                cur = conn.execute(
                    """UPDATE knowledge_chunks
                       SET chunk_text = ?, original_text = ?, language = ?,
                           translated_at = ?, embedding = ?, embedding_dim = ?
                       WHERE id = ?""",
                    (new_text, orig_text, lang, _now_iso(), blob, dim, cid),
                )
                if cur.rowcount == 0:
                    logger.warning(f"  write failed (rowcount=0): {cid[:20]}")
                    continue
                written += 1
                if dim == BGE_DIM:
                    conn.execute(
                        "DELETE FROM knowledge_chunks_vec WHERE rowid = ?",
                        (rowid,),
                    )
                    conn.execute(
                        "INSERT INTO knowledge_chunks_vec(rowid, embedding) VALUES (?, ?)",
                        (rowid, blob),
                    )
            conn.commit()
            logger.debug(f"  _write_batch: committed {written} updates")
        finally:
            conn.close()

    def _print_stats(self) -> None:
        s = self.stats()
        logger.info("=== DB 状态 ===")
        logger.info(f"  total chunks: {s['total_chunks']}")
        for lang, n in s["by_language"].items():
            logger.info(f"  language={lang}: {n}")
        logger.info(f"  to_translate (language IN en/mixed AND translated_at IS NULL): {s['to_translate']}")

    def detect_languages(self, batch_size: int = 2000) -> Dict[str, int]:
        """扫描所有 chunk_text，按启发式更新 language 列（单连接 + 大 batch）。

        一次性全表扫，不再 WHERE 过滤（避免无限循环）。
        """
        conn = self._conn()
        try:
            updated = {"en": 0, "zh": 0, "mixed": 0}
            # 1. 一次拿所有未翻译的 chunk 的 id + text
            rows = conn.execute(
                """SELECT id, chunk_text FROM knowledge_chunks
                   WHERE translated_at IS NULL
                   ORDER BY id"""
            ).fetchall()
            total = len(rows)
            logger.info(f"  total unprocessed: {total} chunks")

            # 2. 内存里 classify，按 batch 写
            pending: List[Tuple[str, str]] = []  # (lang, id)
            for i, r in enumerate(rows):
                lang = detect_language(r["chunk_text"])
                pending.append((lang, r["id"]))
                updated[lang] += 1
                if len(pending) >= batch_size:
                    conn.executemany(
                        "UPDATE knowledge_chunks SET language = ? WHERE id = ?",
                        pending,
                    )
                    conn.commit()
                    pending.clear()
                    logger.info(
                        f"  progress={i+1}/{total} | "
                        f"en={updated['en']}, zh={updated['zh']}, mixed={updated['mixed']}"
                    )
            if pending:
                conn.executemany(
                    "UPDATE knowledge_chunks SET language = ? WHERE id = ?",
                    pending,
                )
                conn.commit()
                pending.clear()
            logger.info(
                f"  done: total={total} | en={updated['en']}, "
                f"zh={updated['zh']}, mixed={updated['mixed']}"
            )
            return updated
        finally:
            conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(PROJECT_ROOT / "data" / "jobhunter_v2.db"))
    ap.add_argument("--batch-size", type=int, default=DEFAULT_BATCH)
    ap.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--detect-only", action="store_true", help="只跑语言检测，不翻译")
    ap.add_argument("--limit", type=int, default=0, help="最多处理 chunks 数（0=全部）")
    args = ap.parse_args()

    runner = BackfillRunner(args.db, args.batch_size, args.concurrency, args.dry_run)
    if args.dry_run:
        runner._print_stats()
        return
    if args.detect_only:
        runner.detect_languages()
        runner._print_stats()
        return
    asyncio.run(runner.run(limit=args.limit))


if __name__ == "__main__":
    main()
