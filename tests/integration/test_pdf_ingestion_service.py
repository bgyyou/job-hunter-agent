# -*- coding: utf-8 -*-
"""P3-1: PdfIngestionService 单元覆盖（不打真 PDF / DB / embedder）。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


SAMPLE_CHUNKS = [
    {"page": 0, "type": "heading", "content": "Senior PM",
     "metadata": {"document_title": "Senior PM"}, "heading_path": []},
    {"page": 1, "type": "paragraph",
     "content": "Build LLM products with stakeholders.",
     "metadata": {"keywords": ["LLM"]}, "heading_path": ["职责"]},
    {"page": 1, "type": "list", "content": "5y exp; Python required.",
     "metadata": {}, "heading_path": ["要求"]},
]


def _patch_pipeline():
    """Patch the heavyweight imports done inside PdfIngestionService methods."""
    parser = MagicMock()
    parser.return_value.parse.return_value = SAMPLE_CHUNKS
    contextualizer = MagicMock()
    contextualizer.return_value.generate_context.side_effect = (
        lambda chunks: [{**c, "context": "ctx"} for c in chunks]
    )
    return parser, contextualizer


def test_ingest_calls_classifier_and_insert_jd():
    from services.pdf_ingestion_service import PdfIngestionService

    parser, contextualizer = _patch_pipeline()
    db = MagicMock()
    db.insert_jd.return_value = "jd-1"
    db.get_jd.return_value = {"id": "jd-1"}
    db.insert_chunks_batch.return_value = ["c1", "c2"]

    classifier = MagicMock()
    classifier.classify.return_value = {
        "industry_tag": "ai", "function_tag": "pm", "position_tag": "senior",
    }

    with patch("document_parser.PDFParser", parser), \
         patch("document_parser.Contextualizer", contextualizer), \
         patch("tools.embedder.Embedder") as MockEmb:
        MockEmb.return_value.embed_batch.return_value = [[0.1] * 8, [0.2] * 8]
        out = PdfIngestionService(db=db, classifier=classifier).ingest("sample.pdf")

    assert out == "jd-1"
    classifier.classify.assert_called_once()
    db.insert_jd.assert_called_once()
    jd_arg = db.insert_jd.call_args[0][0]
    assert jd_arg["source"] == "pdf"
    assert jd_arg["url"].startswith("pdf://")
    assert jd_arg["industry_tag"] == "ai"
    assert jd_arg["auto_classified"] == 1


def test_ingest_persists_chunks_with_embeddings():
    from services.pdf_ingestion_service import PdfIngestionService

    parser, contextualizer = _patch_pipeline()
    db = MagicMock()
    db.insert_jd.return_value = "jd-2"
    db.get_jd.return_value = {"id": "jd-2"}
    db.insert_chunks_batch.return_value = ["c1", "c2"]

    with patch("document_parser.PDFParser", parser), \
         patch("document_parser.Contextualizer", contextualizer), \
         patch("tools.embedder.Embedder") as MockEmb:
        MockEmb.return_value.embed_batch.return_value = [[0.1] * 8, [0.2] * 8]
        PdfIngestionService(db=db, classifier=None).ingest("sample.pdf")

    db.insert_chunks_batch.assert_called_once()
    args = db.insert_chunks_batch.call_args[0]
    jd_id, records = args
    assert jd_id == "jd-2"
    assert len(records) == 2  # skips page-0 meta
    for r in records:
        assert r["embedding"] is not None
        assert r["embedding_dim"] == 8


def test_ingest_recovers_jd_id_when_get_returns_none():
    """insert_jd 的 INSERT OR IGNORE 可能静默跳过；service 应通过 URL 回查。"""
    from services.pdf_ingestion_service import PdfIngestionService

    parser, contextualizer = _patch_pipeline()
    db = MagicMock()
    db.insert_jd.return_value = "fake-uuid"
    db.get_jd.return_value = None  # 模拟 OR IGNORE 静默跳过
    db.get_jd_by_url.return_value = {"id": "real-jd-id"}
    db.insert_chunks_batch.return_value = []

    with patch("document_parser.PDFParser", parser), \
         patch("document_parser.Contextualizer", contextualizer), \
         patch("tools.embedder.Embedder") as MockEmb:
        MockEmb.return_value.embed_batch.return_value = [[0.1] * 8, [0.2] * 8]
        out = PdfIngestionService(db=db).ingest("sample.pdf")

    assert out == "real-jd-id"
    db.get_jd_by_url.assert_called_once()
