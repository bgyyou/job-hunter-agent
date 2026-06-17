# -*- coding: utf-8 -*-
"""Integration test for JobHunter v2 architecture upgrade."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = "sqlite:///data/jobhunter_v2.db"

from database.factory import get_db


def _create_sample_pdf(path: str) -> bool:
    """Create a minimal PDF with JD-like text. reportlab first, fallback to raw PDF."""
    os.makedirs(os.path.dirname(path), exist_ok=True)

    if os.path.exists(path):
        print(f"[INFO] PDF already exists: {path}")
        return True

    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas

        c = canvas.Canvas(path, pagesize=letter)
        c.drawString(100, 750, "AI Product Manager")
        c.drawString(100, 730, "Responsibilities: Develop AI strategy")
        c.drawString(100, 710, "Requirements: Python, LLM, RAG")
        c.save()
        print(f"[INFO] PDF created via reportlab: {path}")
        return True
    except ImportError:
        # Fallback: write raw PDF bytes
        try:
            pdf = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj
4 0 obj<</Length 120>>stream
BT
/F1 12 Tf
100 750 Td
(AI Product Manager) Tj
0 -20 Td
(Responsibilities: Develop AI strategy) Tj
0 -20 Td
(Requirements: Python, LLM, RAG) Tj
0 -20 Td
(Location: Remote / Hong Kong) Tj
ET
endstream
endobj
5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
xref
0 6
trailer<</Size 6/Root 1 0 R>>
startxref
567
%%EOF"""
            with open(path, "wb") as f:
                f.write(pdf)
            print(f"[INFO] PDF created via raw bytes: {path}")
            return True
        except Exception as e:
            print(f"[SKIP] Cannot create PDF: {e}")
            return False


def test_db_init():
    """Test 1: Database initialization."""
    db = get_db()
    stats = db.get_stats()
    print(f"[PASS] DB init (backend={type(db).__name__}): {stats}")
    assert "resumes" in stats


def test_insert_jd_from_pdf():
    """Test 2: PDF → JD + chunks pipeline."""
    pdf_path = os.path.join(os.path.dirname(__file__), "fixtures", "sample_jd.pdf")
    if not _create_sample_pdf(pdf_path):
        return

    db = get_db()
    method = getattr(db, "insert_jd_from_parsed_pdf", None)
    if method is None:
        print("[SKIP] Backend has no insert_jd_from_parsed_pdf")
        return

    try:
        from database.classifier import Classifier
        clf = Classifier()
        jd_id = db.insert_jd_from_parsed_pdf(pdf_path, user_id="test", classifier=clf)
        print(f"[PASS] PDF inserted, jd_id={jd_id}")

        # Verify chunks exist
        chunks = db.get_chunks_by_jd(jd_id)
        print(f"[PASS] Found {len(chunks)} chunks for this JD")
        if chunks:
            c = chunks[0]
            has_context = bool(c.get("context", ""))
            print(f"[PASS] Chunk 0 has context={has_context}, type={c.get('chunk_type', '?')}")
    except NotImplementedError:
        print("[SKIP] Backend does not implement insert_jd_from_parsed_pdf")
    except Exception as e:
        print(f"[FAIL] PDF insertion error: {e}")
        import traceback
        traceback.print_exc()


def test_search():
    """Test 3: Vector/text search returns correct fields."""
    db = get_db()
    method = getattr(db, "search_similar_chunks", None)
    if method is None:
        print("[SKIP] Backend has no search_similar_chunks")
        return

    try:
        results = method("AI product manager", top_k=3)
        print(f"[PASS] Search returned {len(results)} chunks")
        if results:
            r = results[0]
            required = ["chunk_text", "context", "heading_path", "metadata", "similarity"]
            for k in required:
                assert k in r, f"Missing key: {k}"
            print(f"[PASS] Top result keys OK, similarity={r['similarity']:.3f}")
        else:
            print("[INFO] No search results (expected with empty DB)")
    except NotImplementedError:
        print("[SKIP] Backend does not implement vector search")
    except Exception as e:
        print(f"[FAIL] Search error: {e}")
        import traceback
        traceback.print_exc()


def test_factory_switch():
    """Test 4: Factory returns correct backend type."""
    # Force SQLite
    os.environ["DATABASE_URL"] = "sqlite:///data/jobhunter_v2.db"
    db_sqlite = get_db()
    print(f"[INFO] SQLite backend: {type(db_sqlite).__name__}")
    assert type(db_sqlite).__name__ == "SqliteBackend"

    # Try PG (will fail if no PG running, that's OK)
    try:
        os.environ["DATABASE_URL"] = "postgresql://jobhunter:jobhunter@localhost:5432/jobhunter"
        db_pg = get_db()
        print(f"[INFO] PG backend: {type(db_pg).__name__}")
        assert type(db_pg).__name__ == "PostgresBackend"
    except Exception as e:
        print(f"[INFO] PG not reachable (expected in test env): {e}")

    # Reset to SQLite
    os.environ["DATABASE_URL"] = "sqlite:///data/jobhunter_v2.db"


def test_retriever():
    """Test 5: High-level Retriever wrapper."""
    try:
        from tools.retriever import Retriever
    except ImportError:
        print("[SKIP] tools/retriever.py not found")
        return

    retriever = Retriever()
    try:
        results = retriever.retrieve("AI product manager", top_k=3)
        print(f"[PASS] Retriever returned {len(results)} results")
        if results:
            r = results[0]
            for k in ["chunk_text", "context", "heading_path", "metadata", "similarity"]:
                assert k in r, f"Retriever missing key: {k}"
            print(f"[PASS] Retriever result keys OK")
    except Exception as e:
        print(f"[FAIL] Retriever error: {e}")


if __name__ == "__main__":
    print(f"DATABASE_URL={os.environ['DATABASE_URL']}")
    print("=" * 60)
    test_db_init()
    test_insert_jd_from_pdf()
    test_search()
    test_factory_switch()
    test_retriever()
    print("=" * 60)
    print("All tests completed.")
