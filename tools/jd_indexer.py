# -*- coding: utf-8 -*-
"""JD indexing helper — chunk + embed + persist.

v2.1 M3.4: 在 JD 落库后调用，把 raw_text 切分 → 向量化 → 落 knowledge_chunks。

设计上独立于 web_app / crawler，两路入口都能复用；失败只记 warning 不抛，
保证 JD 主流程不被向量化 bug 拖死。
"""
from __future__ import annotations

from typing import Any, Optional

from loguru import logger


def embed_and_store_jd_chunks(
    db: Any,
    jd_id: str,
    raw_text: str,
    user_id: str = "default",
) -> int:
    """切分 + 向量化 + 落库。返回写入的 chunk 数；失败返回 0。"""
    if not raw_text or not raw_text.strip():
        logger.debug(f"[indexer] skip empty raw_text for jd_id={jd_id}")
        return 0

    try:
        from tools.chunker import SemanticChunker
        from tools.embedder import Embedder
    except ImportError as exc:
        logger.warning(f"[indexer] chunker/embedder import failed: {exc}")
        return 0

    chunks = SemanticChunker().split(raw_text)
    if not chunks:
        logger.debug(f"[indexer] no chunks produced for jd_id={jd_id}")
        return 0

    texts = [c.chunk_text for c in chunks]
    try:
        vectors = Embedder().embed_batch(texts)
    except Exception as exc:
        logger.warning(f"[indexer] embedding batch failed: {exc}")
        return 0

    if len(vectors) != len(chunks):
        logger.warning(
            f"[indexer] embed length mismatch: {len(vectors)} vs {len(chunks)}, abort"
        )
        return 0

    records = []
    for c, vec in zip(chunks, vectors):
        records.append({
            "user_id": user_id,
            "chunk_text": c.chunk_text,
            "chunk_type": c.chunk_type,
            "keywords": c.keywords,
            "heading_path": c.heading_path,
            "embedding": vec,
            "embedding_dim": len(vec),
        })

    try:
        ids = db.insert_chunks_batch(jd_id, records)
    except Exception as exc:
        logger.warning(f"[indexer] insert_chunks_batch failed for jd_id={jd_id}: {exc}")
        return 0

    logger.info(
        f"[indexer] jd_id={jd_id} → {len(ids)} chunks indexed "
        f"(types={sorted({c.chunk_type for c in chunks})})"
    )
    return len(ids)
