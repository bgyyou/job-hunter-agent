# -*- coding: utf-8 -*-
"""P1-012 回归：sqlite → PG 迁移覆盖全部 v4 新表，且列拷贝不漏字段。

分三层：
- 静态守卫：TABLE_ORDER 含全部 v4 新表、不含已删的 rag_industry_function，
  且每张表在 PG 侧确实有 CREATE TABLE（否则迁移会静默跳过）
- 纯函数单测：_coerce / _placeholder 的类型转换（CI 无 PG 也能跑，逻辑主体在这）
- e2e：真连 PG 做 sqlite → PG round-trip（无 DATABASE_URL 时 skip）
"""
from __future__ import annotations

import importlib.util
import os
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "scripts" / "migrate_sqlite_to_pg.py"

# v4 引入的新表 —— 上一版 TABLE_ORDER 只有 v2.1 的 6 张，这些全会在 PG 切换时丢
V4_TABLES = {
    "users",
    "flow_a_drafts",
    "jd_structured",
    "rewrite_history",
    "interview_questions",
    "llm_calls",
    "audit_logs",
    "knowledge_chunks",
    "skeleton_cache",
}


@pytest.fixture(scope="module")
def mig():
    """按路径加载脚本模块（scripts/ 不是 package）。"""
    spec = importlib.util.spec_from_file_location("migrate_sqlite_to_pg", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["migrate_sqlite_to_pg"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------- 静态守卫 ----------

def test_table_order_covers_all_v4_tables(mig):
    missing = V4_TABLES - set(mig.TABLE_ORDER)
    assert not missing, f"v4 新表未进迁移清单，PG 切换会丢: {sorted(missing)}"


def test_table_order_excludes_dropped_rag_industry_function(mig):
    """P0-004 已删表，不得进清单（否则迁移必报表不存在）。"""
    assert "rag_industry_function" not in mig.TABLE_ORDER


def test_table_order_has_no_duplicates_and_users_first(mig):
    assert len(mig.TABLE_ORDER) == len(set(mig.TABLE_ORDER))
    # users 是所有 user_id FK 的父表，必须最先迁
    assert mig.TABLE_ORDER[0] == "users"


def test_every_migrated_table_exists_in_pg_schema(mig):
    """清单里的表在 PG 侧必须有 CREATE TABLE，否则运行时静默跳过、迁移空转。"""
    sources = [(PROJECT_ROOT / "data" / "schema_pg.sql").read_text(encoding="utf-8")]
    sources += [p.read_text(encoding="utf-8")
                for p in (PROJECT_ROOT / "database" / "migrations_pg").glob("*.sql")]
    blob = "\n".join(sources)

    for table in mig.TABLE_ORDER:
        assert f"CREATE TABLE IF NOT EXISTS {table} (" in blob, \
            f"{table} 在 TABLE_ORDER 但 PG schema 里没有建表语句"


def test_vec_shadow_tables_are_skipped(mig):
    """sqlite-vec 影子表是 sqlite 内部结构，迁到 PG 没有意义。"""
    assert any(p.startswith("knowledge_chunks_vec") for p in mig.SKIP_PREFIXES)
    assert "schema_version" in mig.SKIP_TABLES


# ---------- 纯函数：类型转换 ----------

def test_placeholder_casts_by_pg_type(mig):
    assert mig._placeholder("jsonb") == "%s::jsonb"
    assert mig._placeholder("vector") == "%s::vector"
    assert mig._placeholder("text") == "%s"
    assert mig._placeholder("int4") == "%s"


def test_coerce_jsonb_passes_valid_json_through(mig):
    assert mig._coerce('{"a": 1}', "jsonb") == '{"a": 1}'
    assert mig._coerce(None, "jsonb") is None


def test_coerce_jsonb_wraps_invalid_json(mig):
    """脏数据不该让整批迁移挂掉。"""
    assert mig._coerce("not json", "jsonb") == '"not json"'


def test_coerce_array_from_json_string(mig):
    assert mig._coerce('["a", "b"]', "_text") == ["a", "b"]
    assert mig._coerce("plain", "_text") == ["plain"]


def test_coerce_bool_from_sqlite_int(mig):
    assert mig._coerce(1, "bool") is True
    assert mig._coerce(0, "bool") is False


# ---------- e2e（需真 PG） ----------

PG_URL = os.environ.get("DATABASE_URL", "")
requires_pg = pytest.mark.skipif(
    not PG_URL.startswith("postgresql://"),
    reason="需要真 PostgreSQL：设 DATABASE_URL=postgresql://... 后重跑",
)


@pytest.fixture
def seeded_sqlite(tmp_path):
    """建一个含 users + jds 的小 sqlite，作为迁移源。"""
    from database.backends.sqlite_backend import SqliteBackend

    db_path = tmp_path / "src.db"
    db = SqliteBackend(db_path=str(db_path))
    from services.auth_service import AuthService

    user = AuthService(db).register_user(email="mig@example.com", password="password123")
    db.insert_jd({
        "url": "https://mig.example/1",
        "title": "AI产品经理",
        "company": "MigCorp",
        "raw_text": "负责 AI 产品。",
        "source": "manual",
        "parsed_sections": {"requirements": ["LLM"]},
        "tags": ["LLM"],
    }, user_id=user["id"])
    return str(db_path), user["id"]


@requires_pg
def test_e2e_migration_writes_all_tables(mig, seeded_sqlite, monkeypatch):
    import psycopg2

    sqlite_path, user_id = seeded_sqlite
    monkeypatch.setattr(sys, "argv", [
        "migrate_sqlite_to_pg.py", "--sqlite", sqlite_path,
        "--pg-url", PG_URL, "--user-id", user_id, "--apply",
    ])
    mig.main()

    conn = psycopg2.connect(PG_URL)
    try:
        with conn.cursor() as cur:
            for table in mig.TABLE_ORDER:
                cur.execute(f"SELECT count(*) FROM {table}")
                assert cur.fetchone()[0] >= 0
    finally:
        conn.close()


@requires_pg
def test_e2e_row_counts_match_source(mig, seeded_sqlite, monkeypatch):
    """round-trip：每张表 sqlite 与 PG 行数一致（容差 0）。"""
    import psycopg2

    sqlite_path, user_id = seeded_sqlite
    monkeypatch.setattr(sys, "argv", [
        "migrate_sqlite_to_pg.py", "--sqlite", sqlite_path,
        "--pg-url", PG_URL, "--user-id", user_id, "--apply",
    ])
    mig.main()

    src = sqlite3.connect(sqlite_path)
    conn = psycopg2.connect(PG_URL)
    try:
        for table in mig.TABLE_ORDER:
            if not mig._sqlite_columns(sqlite_path, table):
                continue
            expected = src.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            with conn.cursor() as cur:
                cur.execute(f"SELECT count(*) FROM {table}")
                assert cur.fetchone()[0] == expected, f"{table} 行数不一致"
    finally:
        src.close()
        conn.close()
