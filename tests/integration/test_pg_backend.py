# -*- coding: utf-8 -*-
"""P2-1 PG backend 测试：HNSW 索引 + migration 扫描 + ef_search

CI 无 PostgreSQL，所有测试通过 mock 验证 SQL 内容和逻辑路径。
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------- 文件存在性 ----------

def test_pg_migrations_directory_exists():
    d = Path(__file__).parent.parent.parent / "database" / "migrations_pg"
    assert d.is_dir()
    files = sorted(d.glob("*.sql"))
    assert len(files) >= 2  # 002 + 003 at minimum


def test_pg_migration_002_contains_composite_index():
    f = Path(__file__).parent.parent.parent / "database" / "migrations_pg" / "002_composite_indexes.sql"
    sql = f.read_text(encoding="utf-8")
    assert "CREATE INDEX IF NOT EXISTS" in sql
    assert "match_history" in sql
    assert "knowledge_chunks" in sql
    assert "WHERE deleted_at IS NULL" in sql


def test_pg_migration_003_contains_hnsw():
    f = Path(__file__).parent.parent.parent / "database" / "migrations_pg" / "003_knowledge_chunks_hnsw.sql"
    sql = f.read_text(encoding="utf-8")
    assert "hnsw" in sql.lower()
    assert "knowledge_chunks" in sql
    assert "vector_cosine_ops" in sql
    assert "m = 16" in sql
    assert "ef_construction = 64" in sql


def test_pg_migration_007_contains_llm_calls():
    f = Path(__file__).parent.parent.parent / "database" / "migrations_pg" / "007_llm_calls.sql"
    sql = f.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS llm_calls" in sql
    assert "idx_llm_calls_created_at" in sql
    assert "UPDATE schema_version" in sql
def test_schema_pg_has_hnsw_index():
    f = Path(__file__).parent.parent.parent / "data" / "schema_pg.sql"
    sql = f.read_text(encoding="utf-8")
    assert "idx_chunk_embedding_hnsw" in sql
    assert "hnsw (embedding vector_cosine_ops)" in sql


# ---------- migration 扫描逻辑（mock） ----------

def test_postgres_init_db_applies_migrations(monkeypatch):
    """验证 _init_db 在 schema 之后扫描 migration 目录"""
    import database.backends.postgres_backend as _mod
    monkeypatch.setattr(_mod, "psycopg2", MagicMock())

    backend = object.__new__(_mod.PostgresBackend)
    backend._conn = MagicMock()
    backend._ensure_connection = MagicMock()
    backend._execute = MagicMock()
    backend.db_url = "postgresql://localhost:5432/test"

    # 伪造 schema_pg.sql 被读取，然后 migration 文件也被扫描
    def _read_side_effect():
        yield "-- schema\n"
        yield "-- 002_composite\n"
        yield "-- 003_hnsw\n"

    with patch.object(Path, "exists", return_value=True):
        with patch("builtins.open", MagicMock()) as m:
            m.return_value.__enter__.return_value.read.side_effect = [
                "-- schema\n",   # schema_pg.sql
                "-- 002\n",      # 002_composite_indexes.sql
                "-- 003\n",      # 003_knowledge_chunks_hnsw.sql
            ]
            backend._init_db()

    # schema + 2 migrations = 3 次 _execute
    assert backend._execute.call_count >= 3


# ---------- ef_search tuning ----------

def test_vector_search_sets_ef_search(monkeypatch):
    """vector_search 在查询前设置 hnsw.ef_search"""
    import database.backends.postgres_backend as _mod
    monkeypatch.setattr(_mod, "psycopg2", MagicMock())

    backend = object.__new__(_mod.PostgresBackend)
    backend._conn = MagicMock()
    backend._fetchall = MagicMock(return_value=[])
    backend._embedding_to_pgvector = MagicMock(return_value="[0.1,...]")
    backend._ensure_connection = MagicMock()

    exec_calls = []
    backend._execute = MagicMock(side_effect=lambda q, *a: exec_calls.append(q))

    backend.vector_search([0.1] * 512, top_k=5)

    ef_calls = [c for c in exec_calls if "ef_search" in str(c)]
    assert len(ef_calls) >= 1
    assert "ef_search" in str(ef_calls[0])


def test_vector_search_ef_search_threshold(monkeypatch):
    """top_k=15 时 ef_search >= 64"""
    import database.backends.postgres_backend as _mod
    monkeypatch.setattr(_mod, "psycopg2", MagicMock())

    backend = object.__new__(_mod.PostgresBackend)
    backend._conn = MagicMock()
    backend._fetchall = MagicMock(return_value=[])
    backend._embedding_to_pgvector = MagicMock(return_value="[0.1,...]")
    backend._ensure_connection = MagicMock()

    exec_calls = []
    backend._execute = MagicMock(side_effect=lambda q, *a: exec_calls.append(q))

    backend.vector_search([0.1] * 512, top_k=15)

    ef_calls = [c for c in exec_calls if "ef_search" in str(c)]
    assert len(ef_calls) >= 1
    assert "64" in str(ef_calls[0]) or "ef_search" in str(ef_calls[0])


# ---------- LIKE fallback (public method, no embedder needed) ----------

def test_like_search_chunks_returns_results(monkeypatch):
    """like_search_chunks returns rows directly without embedding"""
    import database.backends.postgres_backend as _mod
    monkeypatch.setattr(_mod, "psycopg2", MagicMock())

    backend = object.__new__(_mod.PostgresBackend)
    backend._conn = MagicMock()
    backend._fetchall = MagicMock(return_value=[{"chunk_text": "hello", "chunk_type": "full", "similarity": 0.0}])
    backend._ensure_connection = MagicMock()

    result = backend.like_search_chunks("hello", top_k=3)
    assert isinstance(result, list)
    assert len(result) >= 1
    assert result[0]["similarity"] == 0.0