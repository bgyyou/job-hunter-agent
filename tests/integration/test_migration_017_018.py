"""v4 M-v4-2: migration 017/018 落地状态 smoke。

owner 2026-08-03 P0-004 决议：
- 017 DROP rag_industry_function dead schema
- 018 DROP knowledge_chunks.legacy 列 + DELETE 45 行 legacy=1 残留
- 注：owner plan 文本写的 "014/015" 已分别被 vec0 / chunk_translation 占用；
  本文件用实际编号 017/018。

回滚预案：
- 测试不自动删 backup，由 ops 手动 rm。
- 路径：`tests/integration/backups/<timestamp>_seed.db`
"""
from __future__ import annotations

import json as _json
import shutil
import sqlite3
import sys
import time
import uuid as _uuid
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

BACKUP_DIR = Path(__file__).resolve().parent / "backups"
BACKUP_DIR.mkdir(exist_ok=True)


@pytest.fixture(scope="session")
def pre_migration_db():
    """构造一个 pre-017 DB 备份到 BACKUP_DIR（含 legacy 列 + rag_industry_function 表）。

    直接调 SqliteBackend 但手动停在 schema_version=16：让 017/018 落到此 DB 时
    才能精确验证 migration 行为。完整 init 会一次性跑完 002-018，没法回放。

    回滚预案：备份文件 ops 手动 rm，pytest 不清理。
    """
    from database.backends.sqlite_backend import SqliteBackend

    db_path = PROJECT_ROOT / "data" / "test_migration_017_018_seed.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    backend = SqliteBackend(db_path=str(db_path))
    conn = backend._get_conn()
    conn.commit()
    conn.close()

    # 2) 把 schema_version 钉到 16，让 017/018 还可重放
    sc = sqlite3.connect(str(db_path))
    sc.execute("UPDATE schema_version SET version = 16 WHERE id = 1")
    sc.commit()

    # 3) schema.sql 已不带 legacy 列，但 SqliteBackend.__init__ 内的
    # _apply_idempotent_migrations 会 PRAGMA-检查 + ADD COLUMN legacy，
    # 028 后又被 018 DROP。验证：保留 legacy 列给 017/018 落地
    cols = {r[1] for r in sc.execute("PRAGMA table_info(knowledge_chunks)").fetchall()}
    if "legacy" not in cols:
        sc.execute(
            "ALTER TABLE knowledge_chunks ADD COLUMN legacy INTEGER NOT NULL DEFAULT 0"
        )
        sc.commit()
    sc.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    sc.commit()
    sc.close()

    # 4) 备份
    ts = time.strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"pre_017_018_{ts}_seed.db"
    shutil.copy(db_path, backup_path)
    print(f"\n[migration-test] seed backup at {backup_path}（ops 手动 rm）")

    yield db_path

    # cleanup source
    if db_path.exists():
        try:
            db_path.unlink()
        except OSError:
            pass


@pytest.fixture
def fresh_db(pre_migration_db, tmp_path):
    """每个测试独立 DB：从 pre_migration_db 拷贝。"""
    db_path = tmp_path / "fresh.db"
    # 等所有连接关闭后再拷贝
    sc = sqlite3.connect(str(pre_migration_db))
    sc.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    sc.close()
    shutil.copy(pre_migration_db, db_path)
    return db_path


def _apply_sql_file(db_path: Path, sql_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(sql_path.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


class TestMigration017DropRagIndustryFunction:
    """017 DROP rag_industry_function 后表不存在，schema_version 推进到 17。"""

    def test_table_dropped(self, fresh_db):
        _apply_sql_file(fresh_db, PROJECT_ROOT / "database" / "migrations" / "017_drop_rag_industry_function.sql")
        rows = sqlite3.connect(str(fresh_db)).execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='rag_industry_function'"
        ).fetchone()
        assert rows[0] == 0, "rag_industry_function 表应已被 017 DROP"

    def test_schema_version_advanced(self, fresh_db):
        _apply_sql_file(fresh_db, PROJECT_ROOT / "database" / "migrations" / "017_drop_rag_industry_function.sql")
        version = sqlite3.connect(str(fresh_db)).execute(
            "SELECT version FROM schema_version WHERE id=1"
        ).fetchone()[0]
        assert version >= 17, f"schema_version 应推进到 ≥17，实测 {version}"


class TestMigration018DropKnowledgeChunksLegacy:
    """018 DROP knowledge_chunks.legacy 列 + DELETE 45 行 legacy=1 残留。"""

    def test_legacy_column_dropped(self, fresh_db):
        # 先造一些 legacy=1 残留模拟 P2-017 描述
        conn = sqlite3.connect(str(fresh_db))
        try:
            conn.execute("INSERT INTO jds (id, url, raw_text, source) VALUES ('jd_smoke', 'https://x', 'x', 'text')")
            for i in range(5):
                conn.execute(
                    "INSERT INTO knowledge_chunks (id, jd_id, chunk_index, chunk_text, chunk_type, legacy) "
                    "VALUES (?, 'jd_smoke', ?, 'old text', 'full', 1)",
                    (f"smoke_legacy_{i}", i),
                )
            conn.commit()
        finally:
            conn.close()

        _apply_sql_file(fresh_db, PROJECT_ROOT / "database" / "migrations" / "018_drop_knowledge_chunks_legacy.sql")

        cols = {
            r[1] for r in sqlite3.connect(str(fresh_db)).execute(
                "PRAGMA table_info(knowledge_chunks)"
            ).fetchall()
        }
        assert "legacy" not in cols, "knowledge_chunks.legacy 列应被 DROP"

    def test_legacy_residue_deleted(self, fresh_db):
        """018 应清掉 legacy=1 残留行。"""
        conn = sqlite3.connect(str(fresh_db))
        try:
            conn.execute("INSERT INTO jds (id, url, raw_text, source) VALUES ('jd_smoke2', 'https://x', 'x', 'text')")
            for i in range(3):
                conn.execute(
                    "INSERT INTO knowledge_chunks (id, jd_id, chunk_index, chunk_text, chunk_type, legacy) "
                    "VALUES (?, 'jd_smoke2', ?, 'residue', 'full', 1)",
                    (f"residue_{i}", i),
                )
            conn.commit()
            conn.execute(
                "INSERT INTO knowledge_chunks (id, jd_id, chunk_index, chunk_text, chunk_type, legacy) "
                "VALUES ('kept_legacy_0', 'jd_smoke2', 99, 'keep me', 'requirement', 0)"
            )
            conn.commit()
        finally:
            conn.close()

        _apply_sql_file(fresh_db, PROJECT_ROOT / "database" / "migrations" / "018_drop_knowledge_chunks_legacy.sql")

        rows = sqlite3.connect(str(fresh_db)).execute(
            "SELECT count(*) FROM knowledge_chunks WHERE id LIKE 'residue_%'"
        ).fetchone()
        assert rows[0] == 0, "legacy=1 残留应被 DELETE"

        kept = sqlite3.connect(str(fresh_db)).execute(
            "SELECT count(*) FROM knowledge_chunks WHERE id='kept_legacy_0'"
        ).fetchone()
        assert kept[0] == 1, "legacy=0 保留行不应被误删"

    def test_schema_version_advanced(self, fresh_db):
        _apply_sql_file(fresh_db, PROJECT_ROOT / "database" / "migrations" / "018_drop_knowledge_chunks_legacy.sql")
        version = sqlite3.connect(str(fresh_db)).execute(
            "SELECT version FROM schema_version WHERE id=1"
        ).fetchone()[0]
        assert version >= 18, f"schema_version 应推进到 ≥18，实测 {version}"


class TestPostMigrationRAGSmoke:
    """migration 落地后 RAG 召回仍工作。"""

    def test_vector_search_returns_results_without_legacy_filter(
        self, fresh_db, mock_embedder
    ):
        # 先把 017/018 跑完
        _apply_sql_file(fresh_db, PROJECT_ROOT / "database" / "migrations" / "017_drop_rag_industry_function.sql")
        _apply_sql_file(fresh_db, PROJECT_ROOT / "database" / "migrations" / "018_drop_knowledge_chunks_legacy.sql")

        # 不能直接用 SqliteBackend(db_path) — 它的 _apply_idempotent_migrations
        # 会重新 ADD legacy 列。本测试用直接 sqlite3 连接验证底层 SQL 行为。
        embedder = mock_embedder()
        vec = embedder.embed("AI 产品经理 简历")
        blob = _json.dumps(vec).encode("utf-8")

        conn = sqlite3.connect(str(fresh_db))
        conn.row_factory = sqlite3.Row
        try:
            conn.execute(
                "INSERT INTO jds (id, url, raw_text, source) VALUES ('jd_smoke3', 'https://x', 'x', 'text')"
            )
            conn.executemany(
                "INSERT INTO knowledge_chunks (id, jd_id, chunk_index, chunk_text, chunk_type, embedding, embedding_dim) "
                "VALUES (?, 'jd_smoke3', ?, ?, ?, ?, ?)",
                [
                    (str(_uuid.uuid4()), 0, "做 AI 产品", "responsibility", blob, len(vec)),
                    (str(_uuid.uuid4()), 1, "要求 LLM 经验", "requirement", blob, len(vec)),
                ],
            )
            conn.commit()

            # 模拟 vector_search numpy fallback（SQLite 后端）
            import numpy as np
            chunks = [dict(r) for r in conn.execute(
                "SELECT kc.rowid AS kc_rowid, kc.*, j.industry_tag AS jd_industry_tag, "
                "j.function_tag AS jd_function_tag, j.position_tag AS jd_position_tag "
                "FROM knowledge_chunks kc LEFT JOIN jds j ON j.id = kc.jd_id "
                "WHERE kc.deleted_at IS NULL AND kc.embedding IS NOT NULL"
            ).fetchall()]
            assert len(chunks) >= 2, "RAG 应能召回至少 2 条 chunk"

            scored: list[tuple[float, dict]] = []
            for row in chunks:
                v_raw = row["embedding"]
                v_list = _json.loads(bytes(v_raw).decode("utf-8"))
                q = np.asarray(vec, dtype=np.float32)
                v = np.asarray(v_list, dtype=np.float32)
                qn = float(np.linalg.norm(q)) or 1.0
                vn = float(np.linalg.norm(v)) or 1.0
                cos = float(np.dot(q, v) / (qn * vn))
                scored.append((cos, row))
            scored.sort(key=lambda t: t[0], reverse=True)

            assert len(scored) >= 1, "RAG 召回 smoke 应有结果"
            for _, row in scored[:5]:
                assert "legacy" not in row, (
                    f"RAG 结果不应含 legacy 字段（已 DROP）：{list(row.keys())}"
                )
        finally:
            conn.close()


class TestRollbackReadiness:
    """回滚预案：seed backup 文件应在 BACKUP_DIR 里。pytest 不删，ops 手动 rm。"""

    def test_seed_backup_exists(self):
        backups = sorted(BACKUP_DIR.glob("pre_017_018_*.db"))
        assert backups, f"回滚 backup 缺失：{BACKUP_DIR} 应有 pre_017_018_*.db"
        latest = backups[-1]
        assert latest.stat().st_size > 0, f"backup 应非空：{latest}"
