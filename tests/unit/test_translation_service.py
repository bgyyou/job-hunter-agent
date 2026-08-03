import sqlite3

import numpy as np
import pytest
import sqlite_vec

from scripts.backfill_translate_chunks import BGE_DIM, BackfillRunner
from services._text_utils import strip_thinking
from services.translation_service import ChunkTranslator, detect_language


def test_strip_thinking_fenced_block():
    src = "```thinking\nfoo bar\n```\n答案工程经理"
    assert strip_thinking(src) == "答案工程经理"


def test_strip_thinking_plain_tag():
    src = "<think>reasoning here</think>\n答案工程经理"
    assert strip_thinking(src) == "答案工程经理"


def test_strip_thinking_keeps_clean():
    src = "答案工程经理，无需剥离"
    assert strip_thinking(src) == "答案工程经理，无需剥离"



def _create_db(path):
    conn = sqlite3.connect(path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.executescript(
        """
        CREATE TABLE knowledge_chunks (
            id TEXT PRIMARY KEY,
            chunk_text TEXT NOT NULL,
            original_text TEXT,
            language TEXT NOT NULL,
            translated_at TEXT,
            retry_count INTEGER NOT NULL DEFAULT 0,
            embedding BLOB,
            embedding_dim INTEGER NOT NULL DEFAULT 0
        );
        CREATE VIRTUAL TABLE knowledge_chunks_vec USING vec0(
            embedding float[512] distance_metric=cosine
        );
        """
    )
    conn.execute(
        "INSERT INTO knowledge_chunks "
        "(id, chunk_text, language, embedding, embedding_dim) VALUES (?, ?, ?, ?, ?)",
        ("chunk-1", "Engineering manager", "en", bytes(BGE_DIM * 4), BGE_DIM),
    )
    conn.execute(
        "INSERT INTO knowledge_chunks_vec(rowid, embedding) VALUES (?, ?)",
        (1, bytes(BGE_DIM * 4)),
    )
    conn.commit()
    conn.close()


def test_detect_language():
    assert detect_language("This is an English engineering job description.") == "en"
    assert detect_language("这是一个中文软件工程师职位，需要负责后端系统开发。") == "zh"
    assert detect_language("负责开发 Python API and SQL data processing systems") == "mixed"


def test_split_long_text_preserves_content():
    text = ("a" * 3000) + "\n\n" + ("b" * 3000)
    parts = ChunkTranslator._split_long_text(text)

    assert "".join(parts) == text
    assert len(parts) == 2


@pytest.mark.asyncio
async def test_run_writes_translation_and_replaces_vec0(tmp_path, monkeypatch):
    db_path = tmp_path / "chunks.db"
    _create_db(db_path)
    runner = BackfillRunner(str(db_path), batch_size=1, concurrency=1, dry_run=False)

    async def translate_batch(texts, on_done=None):
        return [(texts[0], "工程经理", None)]

    class FakeEmbedder:
        def embed(self, text):
            vec = np.ones(BGE_DIM, dtype=np.float32)
            return vec / np.linalg.norm(vec)

    runner.translator.translate_batch = translate_batch
    monkeypatch.setattr("tools.embedder.Embedder", FakeEmbedder)

    await runner.run(limit=1)

    conn = sqlite3.connect(db_path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    row = conn.execute(
        "SELECT chunk_text, original_text, translated_at, embedding, embedding_dim "
        "FROM knowledge_chunks WHERE id = 'chunk-1'"
    ).fetchone()
    vec_blob = conn.execute(
        "SELECT embedding FROM knowledge_chunks_vec WHERE rowid = 1"
    ).fetchone()[0]
    conn.close()

    assert row[0] == "工程经理"
    assert row[1] == "Engineering manager"
    assert row[2] is not None
    assert row[4] == BGE_DIM
    assert row[3] == vec_blob
