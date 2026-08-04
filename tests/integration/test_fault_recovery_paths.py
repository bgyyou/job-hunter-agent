"""R9-P2 五类故障友好恢复集成测试。

历史：R13b-prep（2026-08-04）落地 R9-P2。覆盖三类新加的故障注入路径：
- LLM 429 → UserFacingError("服务繁忙，请稍后重试", retry=True)
- DB lock 自动重试（≤3 次）；超限转 UserFacingError
- 切库（migrate_sqlite_to_pg）失败时 rollback + 友好错误日志

另外两类（R3 P0-007 超长输入 / R9 P1-001 并发 / R8 P1-012 切库回滚）
之前已落地，本文件不重复，只在新加的 --rollback-on-fail 选项上验证迁移
总开关的"开 / 关"两条路径。

每条测试用 monkeypatch 注入故障，不依赖真实 LLM API / 真 PG 服务。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from database.errors import UserFacingError


# ========================================================================
# 1. LLM 429 → UserFacingError
# ========================================================================

@pytest.mark.asyncio
async def test_llm_429_raises_user_facing_error(monkeypatch):
    """_call_api 抛 RateLimitError 时，analyze() 包装成 UserFacingError(retry=True)。"""
    from tools.llm import LLMMessage, OpenAICompatibleClient, RateLimitError

    client = OpenAICompatibleClient(
        api_key="test-key",
        api_url="https://example.com/v1",
        model="test-model",
        user_id="test-user",
    )
    # 加速 retry（默认 1.2/2.0/3.0 太慢）
    client.retry_delays = (0.0, 0.0, 0.0)

    async def fake_call_api(*args, **kwargs):
        raise RateLimitError("OpenAI-compat 429: rate limit exceeded")

    monkeypatch.setattr(client, "_call_api", fake_call_api)

    with pytest.raises(UserFacingError) as exc_info:
        await client.analyze([LLMMessage(role="user", content="hi")], use_cache=False)

    err = exc_info.value
    assert err.retry is True
    assert "服务繁忙" in err.message or "稍后重试" in err.message


# ========================================================================
# 2 + 3. DB lock 自动重试 / 超限
# ========================================================================

def test_db_lock_auto_retry_succeeds(tmp_path, monkeypatch):
    """第一次 OperationalError('database is locked')，第二次成功；最终应正常返回 jd_id。"""
    from database.backends.sqlite_backend import SqliteBackend

    db = SqliteBackend(db_path=str(tmp_path / "test.db"))
    # 把 base_delay 调到 0 加速
    monkeypatch.setattr(
        "database.backends.sqlite_backend.time.sleep",
        lambda _s: None,
    )

    real_impl = db._insert_jd_impl
    calls = {"n": 0}

    def flaky_impl(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise sqlite3.OperationalError("database is locked")
        return real_impl(*args, **kwargs)

    monkeypatch.setattr(db, "_insert_jd_impl", flaky_impl)

    jd_id = db.insert_jd(
        {"url": "https://example.com/job/1", "title": "t", "company": "c"},
        user_id="u1",
    )

    assert isinstance(jd_id, str)
    assert calls["n"] == 2  # 一次失败 + 一次成功


def test_db_lock_max_retries_exceeded(tmp_path, monkeypatch):
    """持续 lock → 3 次后抛 UserFacingError(retry=True)，不再走原始 sqlite3.OperationalError。"""
    from database.backends.sqlite_backend import SqliteBackend

    db = SqliteBackend(db_path=str(tmp_path / "test.db"))
    monkeypatch.setattr(
        "database.backends.sqlite_backend.time.sleep",
        lambda _s: None,
    )

    def always_locked(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(db, "_insert_jd_impl", always_locked)

    with pytest.raises(UserFacingError) as exc_info:
        db.insert_jd({"url": "https://x/2", "title": "t", "company": "c"}, user_id="u1")

    err = exc_info.value
    assert err.retry is True
    assert "冲突" in err.message or "稍后重试" in err.message


# ========================================================================
# 4 + 5. 切库回滚 — 默认开启 / 显式关闭
# ========================================================================

class _FakeCursor:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *a, **kw):
        return None

    def fetchall(self):
        return []

    def executemany(self, *a, **kw):
        return None


class _FakePgConn:
    def __init__(self, fail_on: str | None = None):
        self.commits: list[str] = []
        self.rollbacks: list[str] = []
        self.autocommit = None
        self.closed = False
        self._fail_on = fail_on

    def cursor(self):
        return _FakeCursor()

    def commit(self):
        self.commits.append("commit")

    def rollback(self):
        self.rollbacks.append("rollback")

    def close(self):
        self.closed = True


def _run_main_with_conn(monkeypatch, conn, *, rollback_on_fail: bool):
    """跑 migrate_sqlite_to_pg.main，把 psycopg2.connect 换成 conn 注入。"""
    import scripts.migrate_sqlite_to_pg as mig

    monkeypatch.setattr(mig, "_sqlite_columns", lambda *_a, **_kw: ["id", "title"])
    monkeypatch.setattr(mig, "_pg_columns", lambda *_a, **_kw: {"id": "int4", "title": "text"})
    monkeypatch.setattr(mig, "_read_all", lambda *_a, **_kw: [{"id": 1, "title": "t"}])
    monkeypatch.setattr(mig, "_resync_sequences", lambda *_a, **_kw: None)
    monkeypatch.setattr(mig, "_copy_table", lambda *_a, **_kw: 1)

    if conn._fail_on == "copy":
        def boom_copy(*_a, **_kw):
            raise RuntimeError("simulated PG failure")
        monkeypatch.setattr(mig, "_copy_table", boom_copy)

    fake_psycopg2 = type("P", (), {"connect": staticmethod(lambda *a, **kw: conn)})
    # scripts/migrate_sqlite_to_pg.py 在 main() 内部 `import psycopg2`，
    # 所以 monkeypatch 目标是全局 psycopg2 模块而非 mig.psycopg2 属性。
    import psycopg2 as _real_psycopg2
    monkeypatch.setattr(_real_psycopg2, "connect", lambda *a, **kw: conn)

    argv = ["migrate_sqlite_to_pg.py", "--user-id", "u1", "--apply"]
    if not rollback_on_fail:
        argv.append("--no-rollback-on-fail")
    monkeypatch.setattr("sys.argv", argv)

    return mig


def test_migration_rollback_on_fail_called(monkeypatch):
    """默认 rollback-on-fail=True：迁移失败时 pg_conn.rollback() 被调用 + conn.close。"""
    import scripts.migrate_sqlite_to_pg as mig

    conn = _FakePgConn(fail_on="copy")
    mig_mod = _run_main_with_conn(monkeypatch, conn, rollback_on_fail=True)

    with pytest.raises(RuntimeError, match="simulated PG failure"):
        mig_mod.main()

    # 核心不变量：失败 → rollback + close
    assert conn.rollbacks == ["rollback"], "rollback 必须在失败时被调用"
    assert conn.closed is True
    # loguru 走 sys.stderr 但 capfd 不会捕获 file descriptor 重定向，
    # 这里不强断言文案（人眼验日志内容），只验副作用。


def test_migration_rollback_skipped_when_disabled(monkeypatch):
    """--no-rollback-on-fail：失败时 rollback 不被调用，conn 仍 close。"""
    import scripts.migrate_sqlite_to_pg as mig

    conn = _FakePgConn(fail_on="copy")
    mig_mod = _run_main_with_conn(monkeypatch, conn, rollback_on_fail=False)

    with pytest.raises(RuntimeError, match="simulated PG failure"):
        mig_mod.main()

    assert conn.rollbacks == [], "--no-rollback-on-fail 时 rollback 不应被调用"
    assert conn.closed is True