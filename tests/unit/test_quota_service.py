# -*- coding: utf-8 -*-
"""v4 T1.4：QuotaService 单测。

复用 conftest 的 tmp_db fixture（临时 sqlite 文件，启动时自动跑
schema.sql + 内联幂等迁移 + 编号迁移文件，llm_calls.user_id 由此落地）。
"""
from __future__ import annotations

import sqlite3

import pytest

from config.settings import Settings
from services.quota_service import (
    GLOBAL_LIMIT_MESSAGE,
    USER_LIMIT_MESSAGE,
    QuotaExceededError,
    QuotaService,
)


def _insert_calls(db, user_id: str, n: int, tokens: int = 10) -> None:
    """经 backend 公共接口写 n 条今天的 llm_calls 记录。"""
    for _ in range(n):
        db.insert_llm_call({
            "model": "test-model",
            "operation": "analyze",
            "total_tokens": tokens
        }, user_id=user_id)


def _limited_settings(monkeypatch, user_limit: int, global_limit: int) -> Settings:
    monkeypatch.setenv("LLM_USER_DAILY_CALL_LIMIT", str(user_limit))
    monkeypatch.setenv("LLM_GLOBAL_DAILY_CALL_LIMIT", str(global_limit))
    return Settings()


class TestCheckQuota:
    def test_under_limit_no_raise(self, tmp_db):
        QuotaService(tmp_db).check_quota("u1")  # 不抛即通过

    def test_user_limit_exceeded(self, tmp_db, monkeypatch):
        settings = _limited_settings(monkeypatch, user_limit=2, global_limit=1000)
        _insert_calls(tmp_db, "u1", 2)
        with pytest.raises(QuotaExceededError) as exc_info:
            QuotaService(tmp_db, settings).check_quota("u1")
        assert str(exc_info.value) == USER_LIMIT_MESSAGE
        assert exc_info.value.scope == "user"

    def test_user_limit_not_shared_across_users(self, tmp_db, monkeypatch):
        """u1 打满不影响 u2。"""
        settings = _limited_settings(monkeypatch, user_limit=2, global_limit=1000)
        _insert_calls(tmp_db, "u1", 2)
        QuotaService(tmp_db, settings).check_quota("u2")  # 不抛即通过

    def test_global_limit_exceeded(self, tmp_db, monkeypatch):
        settings = _limited_settings(monkeypatch, user_limit=1000, global_limit=3)
        _insert_calls(tmp_db, "u1", 2)
        _insert_calls(tmp_db, "u2", 1)
        with pytest.raises(QuotaExceededError) as exc_info:
            QuotaService(tmp_db, settings).check_quota("u1")
        assert str(exc_info.value) == GLOBAL_LIMIT_MESSAGE
        assert exc_info.value.scope == "global"

    def test_global_limit_takes_precedence(self, tmp_db, monkeypatch):
        """两档同时超限时报全局熔断文案。"""
        settings = _limited_settings(monkeypatch, user_limit=2, global_limit=2)
        _insert_calls(tmp_db, "u1", 2)
        with pytest.raises(QuotaExceededError) as exc_info:
            QuotaService(tmp_db, settings).check_quota("u1")
        assert exc_info.value.scope == "global"


class TestGetUsageToday:
    def test_counts_calls_and_tokens(self, tmp_db):
        _insert_calls(tmp_db, "u1", 3, tokens=10)
        _insert_calls(tmp_db, "u2", 2, tokens=7)
        usage = QuotaService(tmp_db).get_usage_today("u1")
        assert usage == {"calls": 3, "tokens": 30}

    def test_empty_db_returns_zero(self, tmp_db):
        assert QuotaService(tmp_db).get_usage_today("u1") == {"calls": 0, "tokens": 0}

    def test_yesterday_not_counted(self, tmp_db):
        """直接写一条昨天的记录，验证当天口径 date(created_at)=date('now')。"""
        conn = sqlite3.connect(tmp_db.db_path)
        try:
            conn.execute(
                """
                INSERT INTO llm_calls (model, operation, total_tokens, user_id, created_at)
                VALUES ('test-model', 'analyze', 99, 'u1', datetime('now', '-1 day'))
                """
            )
            conn.commit()
        finally:
            conn.close()
        _insert_calls(tmp_db, "u1", 1, tokens=10)
        assert QuotaService(tmp_db).get_usage_today("u1") == {"calls": 1, "tokens": 10}


class TestLimitSettings:
    def test_limits_readable_from_env(self, monkeypatch):
        monkeypatch.setenv("LLM_USER_DAILY_CALL_LIMIT", "7")
        monkeypatch.setenv("LLM_GLOBAL_DAILY_CALL_LIMIT", "123")
        s = Settings()
        assert s.llm_user_daily_call_limit == 7
        assert s.llm_global_daily_call_limit == 123

    def test_limits_defaults(self, monkeypatch):
        monkeypatch.delenv("LLM_USER_DAILY_CALL_LIMIT", raising=False)
        monkeypatch.delenv("LLM_GLOBAL_DAILY_CALL_LIMIT", raising=False)
        s = Settings()
        assert s.llm_user_daily_call_limit == 50
        assert s.llm_global_daily_call_limit == 2000
