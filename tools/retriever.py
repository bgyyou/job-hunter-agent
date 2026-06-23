# -*- coding: utf-8 -*-
"""Retriever — thin facade over `services.retrieval_service.RetrievalService`.

Kept as a stable import path for prod callers (`web_app.py`, `agents/resume_flow_a.py`).
The actual retrieval flow (embed → vector_search → chunk_type weighting → min_similarity)
lives in the service layer; this class just forwards.
"""

from typing import Any, Dict, List, Optional


class Retriever:
    """High-level RAG entry point. Wraps ``RetrievalService``.

    Usage:
        retriever = Retriever()
        results = retriever.retrieve("Python后端开发", top_k=5)
    """

    def __init__(self, db: Any = None):
        self._db = db
        self._service = None

    def _get_service(self):
        if self._service is None:
            from services.retrieval_service import RetrievalService
            self._service = RetrievalService(db=self._db)
        return self._service

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        filter_chunk_type: Optional[str] = None,
        user_id: Optional[str] = None,
        min_similarity: float = 0.55,
    ) -> List[Dict]:
        """Forward to ``RetrievalService.retrieve``. See that for shape."""
        return self._get_service().retrieve(
            query=query,
            top_k=top_k,
            filter_chunk_type=filter_chunk_type,
            user_id=user_id,
            min_similarity=min_similarity,
        )
