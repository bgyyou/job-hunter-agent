# -*- coding: utf-8 -*-
"""PDF ingestion service — owns the PDF → JD + chunks pipeline.

Pulled out of `SqliteBackend.insert_jd_from_parsed_pdf` / `PostgresBackend.insert_jd_from_parsed_pdf`
in P3-1. The two backends previously had divergent implementations:

- SQLite wrote to `knowledge_chunks` without embeddings
- PG embedded per-chunk and wrote to the legacy `chunks_vector` table

This service consolidates to a single flow that writes to `knowledge_chunks`
with embeddings via `db.insert_chunks_batch(...)`, identical on both backends.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger


# document_parser chunk type → DB chunk_type enum
_TYPE_MAP = {
    "heading": "full",
    "paragraph": "full",
    "list": "full",
    "table": "full",
    "figure": "full",
    "footnote": "full",
}


class PdfIngestionService:
    """Parse a PDF, enrich its chunks, and persist as a JD + knowledge_chunks rows."""

    def __init__(self, db: Any = None, classifier: Any = None):
        self._db = db
        self.classifier = classifier

    def _get_db(self) -> Any:
        if self._db is None:
            from database.factory import get_db
            self._db = get_db()
        return self._db

    def ingest(self, pdf_path: str, user_id: str = "default") -> str:
        """End-to-end pipeline. Returns the persisted `jd_id`."""
        db = self._get_db()

        chunks = self._parse(pdf_path)
        self._describe_figures(chunks)
        chunks = self._contextualize(chunks)

        jd_data = self._build_jd_data(pdf_path, chunks)
        jd_data["user_id"] = user_id
        if self.classifier is not None:
            self._apply_classifier(jd_data)

        jd_id = db.insert_jd(jd_data)

        # Defensive: re-resolve id via URL (INSERT OR IGNORE may have skipped)
        existing = db.get_jd(jd_id)
        if existing is None:
            existing = db.get_jd_by_url(jd_data["url"])
            if existing:
                jd_id = existing["id"]
                logger.info(f"JD already exists by URL: {jd_id}")

        records = self._build_chunk_records(chunks, jd_id, user_id)
        if records:
            self._embed_and_attach(records)
            inserted = db.insert_chunks_batch(jd_id, records)
            logger.info(f"PdfIngestionService: inserted {len(inserted)} chunks for JD {jd_id}")

        return jd_id

    # ---- pipeline steps -----------------------------------------------------

    def _parse(self, pdf_path: str) -> List[Dict]:
        from document_parser import PDFParser
        parser = PDFParser(document_title=Path(pdf_path).stem)
        chunks = parser.parse(pdf_path)
        logger.info(f"PdfIngestionService: parsed {pdf_path} → {len(chunks)} chunks")
        return chunks

    def _describe_figures(self, chunks: List[Dict]) -> None:
        if not any(c.get("type") == "figure" for c in chunks):
            return
        try:
            from document_parser import MultimodalDescriber
            MultimodalDescriber().describe_figures(chunks)
        except Exception as exc:
            logger.warning(f"Figure description skipped: {exc}")

    def _contextualize(self, chunks: List[Dict]) -> List[Dict]:
        try:
            from document_parser import Contextualizer
            return Contextualizer().generate_context(chunks)
        except Exception as exc:
            logger.warning(f"Context generation skipped: {exc}")
            for c in chunks:
                c.setdefault("context", "[context unavailable]")
            return chunks

    def _build_jd_data(self, pdf_path: str, chunks: List[Dict]) -> Dict:
        meta_chunk = next((c for c in chunks if c.get("page") == 0), None)
        meta = (meta_chunk.get("metadata", {}) if meta_chunk else {}) or {}
        doc_title = (
            meta.get("document_title", "")
            or (meta_chunk.get("content", "") if meta_chunk else "")
            or Path(pdf_path).stem
        ).strip()
        para_texts = [c.get("content", "") for c in chunks if c.get("type") in ("paragraph", "list")]
        raw_text = "\n".join(para_texts)[:2000]
        url = f"pdf://{Path(pdf_path).name}"

        now = datetime.now().isoformat()
        return {
            "url": url,
            "title": doc_title,
            "company": "",
            "location": "",
            "salary_str": None,
            "salary_min": None,
            "salary_max": None,
            "parsed_sections": {},
            "tags": [],
            "raw_text": raw_text,
            "source": "pdf",
            "search_keyword": None,
            "platform": None,
            "job_id": None,
            "language": "zh",
            "industry_tag": None,
            "function_tag": None,
            "position_tag": None,
            "auto_classified": 0,
            "is_public": 0,
            "crawled_at": now,
            "created_at": now,
            "updated_at": now,
        }

    def _apply_classifier(self, jd_data: Dict) -> None:
        try:
            result = self.classifier.classify(jd_data["title"], jd_data["raw_text"])
            if isinstance(result, dict):
                jd_data["industry_tag"] = result.get("industry_tag")
                jd_data["function_tag"] = result.get("function_tag")
                jd_data["position_tag"] = result.get("position_tag")
                jd_data["auto_classified"] = 1
                logger.info(
                    f"Classified PDF JD '{jd_data['title']}': "
                    f"industry={jd_data['industry_tag']}, function={jd_data['function_tag']}, "
                    f"position={jd_data['position_tag']}"
                )
        except Exception as exc:
            logger.warning(f"Classification failed: {exc}")

    def _build_chunk_records(self, chunks: List[Dict], jd_id: str, user_id: str) -> List[Dict]:
        records: List[Dict] = []
        for i, chunk in enumerate(chunks):
            if chunk.get("page") == 0:
                continue  # skip meta chunk
            records.append({
                "user_id": user_id,
                "jd_id": jd_id,
                "chunk_index": i,
                "chunk_text": chunk.get("content", ""),
                "chunk_type": _TYPE_MAP.get(chunk.get("type", "full"), "full"),
                "keywords": chunk.get("metadata", {}).get("keywords", []),
                "embedding": None,
                "embedding_dim": None,
                "context": chunk.get("context", ""),
                "heading_path": chunk.get("heading_path", []),
            })
        return records

    def _embed_and_attach(self, records: List[Dict]) -> None:
        """Embed each chunk's text and attach to record. Failures are non-fatal."""
        try:
            from tools.embedder import Embedder
            embedder = Embedder()
            texts = [r["chunk_text"] for r in records]
            vectors = embedder.embed_batch(texts)
        except Exception as exc:
            logger.warning(f"Embedder unavailable; chunks persisted without vectors: {exc}")
            return

        if len(vectors) != len(records):
            logger.warning(
                f"Embedding count mismatch ({len(vectors)} vs {len(records)} records); "
                f"chunks persisted without vectors"
            )
            return

        for rec, vec in zip(records, vectors):
            rec["embedding"] = vec
            rec["embedding_dim"] = len(vec) if vec is not None else None
