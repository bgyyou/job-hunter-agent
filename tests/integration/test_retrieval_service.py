# -*- coding: utf-8 -*-
"""P3-1: RetrievalService 单元覆盖（不打真 DB / embedder）。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from services.retrieval_service import CHUNK_TYPE_WEIGHT, RetrievalService


def _mock_db(rows):
    db = MagicMock()
    db.vector_search = MagicMock(return_value=rows)
    db.like_search_chunks = MagicMock(return_value=rows)
    return db


def test_retrieve_applies_chunk_type_weight():
    """同 similarity 下 requirement (1.3) 应排在 nice_to_have (0.5) 前。"""
    rows = [
        {"chunk_text": "nice", "chunk_type": "nice_to_have", "similarity": 0.7},
        {"chunk_text": "req",  "chunk_type": "requirement",  "similarity": 0.7},
        {"chunk_text": "ovr",  "chunk_type": "overview",     "similarity": 0.7},
    ]
    db = _mock_db(rows)
    with patch("tools.embedder.Embedder") as MockEmb:
        MockEmb.return_value.embed.return_value = [0.1] * 8
        out = RetrievalService(db=db).retrieve("q", top_k=3, min_similarity=0.0)
    assert out[0]["chunk_type"] == "requirement"
    assert out[1]["chunk_type"] == "overview"
    assert out[2]["chunk_type"] == "nice_to_have"


def test_retrieve_falls_back_to_like_when_embedder_unavailable():
    rows = [{"chunk_text": "x", "chunk_type": "full", "similarity": 0.0}]
    db = _mock_db(rows)
    with patch("tools.embedder.Embedder", side_effect=RuntimeError("no model")):
        out = RetrievalService(db=db).retrieve("q", top_k=2)
    db.like_search_chunks.assert_called_once()
    db.vector_search.assert_not_called()
    assert out and out[0]["chunk_text"] == "x"


def test_retrieve_filters_below_min_similarity(monkeypatch):
    """P3-1 旧行为：rerank OFF 时 min_similarity 仍是有效过滤（rerank ON 时被旁路）。"""
    monkeypatch.setenv("RERANKER_ENABLED", "false")
    rows = [
        {"chunk_text": "high", "chunk_type": "full", "similarity": 0.8},
        {"chunk_text": "low",  "chunk_type": "full", "similarity": 0.3},
    ]
    db = _mock_db(rows)
    with patch("tools.embedder.Embedder") as MockEmb:
        MockEmb.return_value.embed.return_value = [0.1] * 8
        out = RetrievalService(db=db).retrieve("q", top_k=5, min_similarity=0.5)
    assert len(out) == 1
    assert out[0]["chunk_text"] == "high"


def test_retrieve_normalizes_output_fields(monkeypatch):
    """rerank OFF 时 ranked_score = sim × chunk_type_weight（legacy 公式）。"""
    monkeypatch.setenv("RERANKER_ENABLED", "false")
    rows = [{"chunk_text": "t", "chunk_type": "requirement", "similarity": 0.9,
             "context": "ctx", "heading_path": ["A", "B"]}]
    db = _mock_db(rows)
    with patch("tools.embedder.Embedder") as MockEmb:
        MockEmb.return_value.embed.return_value = [0.1] * 8
        out = RetrievalService(db=db).retrieve("q", top_k=1, min_similarity=0.0)
    r = out[0]
    for key in ("chunk_text", "context", "heading_path", "chunk_type",
                "chunk_weight", "metadata", "similarity", "ranked_score"):
        assert key in r
    assert r["chunk_weight"] == CHUNK_TYPE_WEIGHT["requirement"]
    assert r["ranked_score"] == round(0.9 * CHUNK_TYPE_WEIGHT["requirement"], 4)


def test_retrieve_overfetches_candidate_k():
    """P1-模块 5：rerank 默认开启 → top_k 传给 backend = max(top_k*5, 50)。"""
    rows = []
    db = _mock_db(rows)
    with patch("tools.embedder.Embedder") as MockEmb, \
         patch("tools.reranker.CrossEncoderReranker") as MockRR:
        MockEmb.return_value.embed.return_value = [0.1] * 8
        MockRR.return_value.rerank.return_value = rows
        RetrievalService(db=db).retrieve("q", top_k=4)
    _args, kwargs = db.vector_search.call_args
    assert kwargs["top_k"] == 50  # max(4*5, 50)


def test_retrieve_overfetches_legacy_when_rerank_disabled(monkeypatch):
    """RERANKER_ENABLED=false → 退回 max(top_k*3, top_k)。"""
    monkeypatch.setenv("RERANKER_ENABLED", "false")
    rows = []
    db = _mock_db(rows)
    with patch("tools.embedder.Embedder") as MockEmb:
        MockEmb.return_value.embed.return_value = [0.1] * 8
        RetrievalService(db=db).retrieve("q", top_k=4)
    _args, kwargs = db.vector_search.call_args
    assert kwargs["top_k"] == 12  # 4 * 3


def test_retrieve_rerank_reorders_candidates():
    """rerank 重排后取 rerank_score_norm 主导，softmax-style。"""
    # mock reranker：把"second"的 rerank 拉到最高
    rows = [
        {"chunk_text": "first",  "chunk_type": "full", "similarity": 0.9},
        {"chunk_text": "second", "chunk_type": "requirement", "similarity": 0.5},
        {"chunk_text": "third",  "chunk_type": "full", "similarity": 0.6},
    ]
    reranked = [
        {**rows[1], "rerank_score": 9.0,  "rerank_score_norm": 0.999},
        {**rows[2], "rerank_score": 3.0,  "rerank_score_norm": 0.953},
        {**rows[0], "rerank_score": -5.0, "rerank_score_norm": 0.007},
    ]
    db = _mock_db(rows)
    with patch("tools.embedder.Embedder") as MockEmb, \
         patch("tools.reranker.CrossEncoderReranker") as MockRR:
        MockEmb.return_value.embed.return_value = [0.1] * 8
        MockRR.return_value.rerank.return_value = reranked
        out = RetrievalService(db=db).retrieve("q", top_k=3, min_similarity=0.0)
    # reranker 重排后即便 similarity 低也应排第一
    assert out[0]["chunk_text"] == "second"
    assert out[0]["rerank_score"] == 9.0


def test_retrieve_rerank_skips_min_similarity():
    """rerank ON 时 sim < min_similarity 不再丢弃（rerank_score 替代评估）。"""
    rows = [
        # cosine 极低但 rerank 高 → 应被保留
        {"chunk_text": "x", "chunk_type": "full", "similarity": 0.01},
    ]
    reranked = [
        {**rows[0], "rerank_score": 7.0, "rerank_score_norm": 0.999},
    ]
    db = _mock_db(rows)
    with patch("tools.embedder.Embedder") as MockEmb, \
         patch("tools.reranker.CrossEncoderReranker") as MockRR:
        MockEmb.return_value.embed.return_value = [0.1] * 8
        MockRR.return_value.rerank.return_value = reranked
        out = RetrievalService(db=db).retrieve("q", top_k=1, min_similarity=0.5)
    assert len(out) == 1
