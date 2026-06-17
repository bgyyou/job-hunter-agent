# -*- coding: utf-8 -*-
"""Retriever — high-level vector search wrapper for Agent use.

Uses database.factory.get_db() to obtain the backend (SQLite or PostgreSQL).
Delegates actual retrieval to backend.search_similar_chunks().
"""

from typing import Any, Dict, List, Optional

from loguru import logger


class Retriever:
    """Encapsulates vector similarity search over knowledge chunks.

    Usage:
        retriever = Retriever()
        results = retriever.retrieve("Python后端开发", top_k=5)
    """

    def __init__(self, db: Any = None):
        """
        Args:
            db: Optional pre-wired database backend.  If None, get_db()
                is called inside retrieve() to obtain one lazily.
        """
        self._db = db

    def _get_db(self) -> Any:
        """Obtain the database backend, creating one if needed."""
        if self._db is None:
            from database.factory import get_db
            self._db = get_db()
        return self._db

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        filter_chunk_type: Optional[str] = None,
        user_id: Optional[str] = None,
        min_similarity: float = 0.55,
    ) -> List[Dict]:
        """Search for chunks similar to *query* using vector embeddings.

        Args:
            query: Search query text.
            top_k: Maximum number of results.
            filter_chunk_type: If set, only return chunks of this type
                               (e.g. "responsibility").
            user_id: If set, scope results to this user.
            min_similarity: v2.1 M3.5 — 余弦相似度阈值，低于此值不返回。
                            设 0.0 可关闭过滤。

        Returns:
            List of dicts, each containing at least:

            - ``chunk_text`` — raw chunk content
            - ``context`` — context description
            - ``heading_path`` — ancestor heading list
            - ``chunk_type`` — overview/responsibility/requirement/nice_to_have
            - ``chunk_weight`` — chunk_type 权重
            - ``metadata`` — dict with source/title/version info
            - ``similarity`` — float in [0, 1]
            - ``ranked_score`` — similarity * chunk_weight（排序依据）

            Empty list if the backend does not support vector search
            or no results are found.
        """
        db = self._get_db()
        method = getattr(db, "search_similar_chunks", None)
        if method is None:
            logger.warning("Database backend has no search_similar_chunks method.")
            return []

        try:
            results = method(
                query_text=query,
                top_k=top_k,
                filter_chunk_type=filter_chunk_type,
                user_id=user_id,
            )
        except Exception as exc:
            logger.warning(f"Vector search failed: {exc}")
            return []

        # Normalize: ensure every result has the required keys
        normalized = []
        for r in results:
            sim = float(r.get("similarity", 0.0))
            if sim < min_similarity:
                continue
            entry = {
                "chunk_text": r.get("chunk_text", ""),
                "context": r.get("context", r.get("chunk_context", "")),
                "heading_path": r.get("heading_path", []),
                "chunk_type": r.get("chunk_type", "full"),
                "chunk_weight": float(r.get("chunk_weight", 1.0)),
                "metadata": r.get("metadata", {}),
                "similarity": sim,
                "ranked_score": float(r.get("ranked_score", sim)),
            }
            normalized.append(entry)

        logger.info(
            f"Retriever: returned {len(normalized)}/{len(results)} results "
            f"for '{query[:50]}...' (top_k={top_k}, min_sim={min_similarity})"
        )
        return normalized
