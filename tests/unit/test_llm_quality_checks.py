# -*- coding: utf-8 -*-
"""Tests for OpenAICompatibleClient quality_checks instrumentation.

埋点目标：每次 LLM 调用（成功 / 失败 / 缓存命中）落一条 quality_checks
记录 latency_ms / tokens / cache_hit / ok / error，便于复盘延迟分布与命中率。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from tools.llm import LLMMessage, LLMResponse, OpenAICompatibleClient


def _make_client(tmp_path):
    return OpenAICompatibleClient(
        api_key="sk-FAKEKEY",
        api_url="https://example.invalid/v1",
        model="agnes-2.0-flash",
        cache_dir=str(tmp_path / "llm_cache"),
    )


def test_record_quality_check_writes_to_db(tmp_db, monkeypatch, tmp_path):
    """直接测 _record_quality_check：mock get_db，确认正确字段被传入。"""
    client = _make_client(tmp_path)

    # 把模块级 get_db patch 成返回 tmp_db
    import database.factory as factory_mod
    monkeypatch.setattr(factory_mod, "get_db", lambda: tmp_db)

    client._record_quality_check(
        latency_ms=137, tokens=256, cache_hit=False, ok=True, error=None,
    )

    rows = tmp_db.list_quality_checks(check_type="llm_call")
    assert len(rows) == 1
    row = rows[0]
    assert row["check_type"] == "llm_call"
    assert row["target_table"] == "llm_calls"
    assert row["score"] == 100.0
    assert row["details"]["latency_ms"] == 137
    assert row["details"]["tokens"] == 256
    assert row["details"]["cache_hit"] is False
    assert row["details"]["ok"] is True


def test_record_quality_check_records_failure(tmp_db, monkeypatch, tmp_path):
    """失败路径：score=0、ok=False、error 入库。"""
    client = _make_client(tmp_path)
    import database.factory as factory_mod
    monkeypatch.setattr(factory_mod, "get_db", lambda: tmp_db)

    client._record_quality_check(
        latency_ms=2000, tokens=0, cache_hit=False, ok=False, error="timeout",
    )

    row = tmp_db.list_quality_checks(check_type="llm_call")[0]
    assert row["score"] == 0.0
    assert row["details"]["ok"] is False
    assert row["details"]["error"] == "timeout"


def test_record_quality_check_swallows_db_errors(tmp_path, monkeypatch):
    """埋点失败绝不影响业务：模拟 get_db 抛异常，确认不向上传播。"""
    client = _make_client(tmp_path)

    def boom():
        raise RuntimeError("db unavailable")

    import database.factory as factory_mod
    monkeypatch.setattr(factory_mod, "get_db", boom)

    # 不应该 raise
    client._record_quality_check(latency_ms=10, tokens=1, cache_hit=False, ok=True, error=None)


def test_analyze_records_quality_check_on_success(tmp_db, monkeypatch, tmp_path):
    """端到端：mock _call_api，调 analyze，验证 quality_checks 写入。"""
    client = _make_client(tmp_path)
    import database.factory as factory_mod
    monkeypatch.setattr(factory_mod, "get_db", lambda: tmp_db)

    async def fake_call_api(messages, max_tokens, temperature):
        return {
            "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 99},
            "model": client.model,
        }

    monkeypatch.setattr(client, "_call_api", fake_call_api)

    asyncio.run(client.analyze(
        [LLMMessage(role="user", content="hello")],
        use_cache=False,
    ))

    rows = tmp_db.list_quality_checks(check_type="llm_call")
    assert len(rows) == 1
    assert rows[0]["details"]["tokens"] == 99
    assert rows[0]["details"]["cache_hit"] is False
    assert rows[0]["details"]["ok"] is True
    assert rows[0]["details"]["latency_ms"] >= 0


def test_analyze_records_quality_check_on_cache_hit(tmp_db, monkeypatch, tmp_path):
    """缓存命中也要落一条，cache_hit=True、latency_ms=0。"""
    client = _make_client(tmp_path)
    import database.factory as factory_mod
    monkeypatch.setattr(factory_mod, "get_db", lambda: tmp_db)

    cached_resp = LLMResponse(content="cached", model=client.model, tokens_used=11, finish_reason="stop")
    monkeypatch.setattr(client, "_get_cache", lambda key: cached_resp)

    asyncio.run(client.analyze(
        [LLMMessage(role="user", content="hello")],
        use_cache=True,
    ))

    rows = tmp_db.list_quality_checks(check_type="llm_call")
    assert len(rows) == 1
    assert rows[0]["details"]["cache_hit"] is True
    assert rows[0]["details"]["latency_ms"] == 0
    assert rows[0]["details"]["tokens"] == 11


def test_analyze_records_quality_check_on_failure(tmp_db, monkeypatch, tmp_path):
    """API 抛错 → 落失败记录 → 异常向上传播。"""
    client = _make_client(tmp_path)
    import database.factory as factory_mod
    monkeypatch.setattr(factory_mod, "get_db", lambda: tmp_db)

    async def boom_call_api(messages, max_tokens, temperature):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(client, "_call_api", boom_call_api)

    with pytest.raises(RuntimeError, match="connection refused"):
        asyncio.run(client.analyze(
            [LLMMessage(role="user", content="hello")],
            use_cache=False,
        ))

    rows = tmp_db.list_quality_checks(check_type="llm_call")
    assert len(rows) == 1
    assert rows[0]["details"]["ok"] is False
    assert "connection refused" in rows[0]["details"]["error"]
