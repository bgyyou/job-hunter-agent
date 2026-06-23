# -*- coding: utf-8 -*-
"""Retrieval service — owns the RAG read path.

Pulled out of `SqliteBackend.search_similar_chunks` / `PostgresBackend.search_similar_chunks`
in P3-1. Backends now expose only `vector_search` (dialect-specific cosine query) and
`like_search_chunks` (LIKE fallback); this service handles:

- Embedding the query
- Over-fetching candidates
- chunk_type weighting & re-ranking
- min_similarity filtering
- Output normalization
- Graceful fallback when the embedder is unavailable
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from loguru import logger


# chunk_type → ranking multiplier. Same numbers both backends used to duplicate.
CHUNK_TYPE_WEIGHT: Dict[str, float] = {
    "responsibility": 1.2,
    "requirement": 1.3,
    "overview": 0.8,
    "nice_to_have": 0.5,
    "full": 1.0,
}


class RetrievalService:
    """RAG retrieval orchestrator. Sits in front of any `BaseBackend`."""

    def __init__(self, db: Any = None):
        self._db = db

    def _get_db(self) -> Any:
        if self._db is None:
            from database.factory import get_db
            self._db = get_db()
        return self._db

    def _embed_query(self, query: str) -> Optional[List[float]]:
        try:
            from tools.embedder import Embedder
            return Embedder().embed(query)
        except Exception as exc:
            logger.warning(f"Embedder unavailable, will fall back to LIKE: {exc}")
            return None

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        filter_chunk_type: Optional[str] = None,
        user_id: Optional[str] = None,
        min_similarity: float = 0.55,
    ) -> List[Dict]:
        """Return up to `top_k` chunks ranked by cosine × chunk_type weight.

        Falls back to LIKE search when the embedder cannot produce a vector.
        Results with `similarity < min_similarity` are dropped after ranking.
        """
        db = self._get_db()
        q_vec = self._embed_query(query)
        if q_vec is None:
            return self._fallback(db, query, top_k, filter_chunk_type, user_id)

        candidate_k = max(top_k * 3, top_k)
        try:
            candidates = db.vector_search(
                query_embedding=q_vec,
                top_k=candidate_k,
                filter_chunk_type=filter_chunk_type,
                user_id=user_id,
            )
        except Exception as exc:
            logger.warning(f"vector_search failed, falling back to LIKE: {exc}")
            return self._fallback(db, query, top_k, filter_chunk_type, user_id)

        scored: List[tuple] = []
        for row in candidates:
            sim = float(row.get("similarity", 0.0) or 0.0)
            ct = row.get("chunk_type") or "full"
            weight = CHUNK_TYPE_WEIGHT.get(ct, 1.0)
            scored.append((sim * weight, sim, ct, weight, row))

        scored.sort(key=lambda t: t[0], reverse=True)

        normalized: List[Dict] = []
        for ranked, sim, ct, weight, row in scored[:top_k]:
            if sim < min_similarity:
                continue
            normalized.append({
                "chunk_text": row.get("chunk_text", ""),
                "context": row.get("context", row.get("chunk_context", "")),
                "heading_path": row.get("heading_path") or [],
                "chunk_type": ct,
                "chunk_weight": weight,
                "metadata": row.get("metadata", {}) or {
                    "jd_id": row.get("jd_id"),
                    "chunk_index": row.get("chunk_index"),
                },
                "similarity": round(sim, 4),
                "ranked_score": round(ranked, 4),
            })

        logger.info(
            f"RetrievalService: returned {len(normalized)}/{len(candidates)} results "
            f"for '{query[:50]}...' (top_k={top_k}, min_sim={min_similarity})"
        )
        return normalized

    def _fallback(self, db, query, top_k, filter_chunk_type, user_id) -> List[Dict]:
        try:
            rows = db.like_search_chunks(
                query_text=query,
                top_k=top_k,
                filter_chunk_type=filter_chunk_type,
                user_id=user_id,
            )
        except Exception as exc:
            logger.warning(f"LIKE fallback failed: {exc}")
            return []

        normalized = []
        for row in rows:
            normalized.append({
                "chunk_text": row.get("chunk_text", ""),
                "context": row.get("context", "") or "",
                "heading_path": row.get("heading_path") or [],
                "chunk_type": row.get("chunk_type", "full") or "full",
                "chunk_weight": CHUNK_TYPE_WEIGHT.get(row.get("chunk_type") or "full", 1.0),
                "metadata": row.get("metadata", {}) or {},
                "similarity": 0.0,
                "ranked_score": 0.0,
            })
        return normalized
