# -*- coding: utf-8 -*-
"""v2.1 N4: OpenAICompatibleClient + LLMClient 基础工具单测。

覆盖目标：
- token 估算与消息计数
- 缓存键稳定性 / set 与 get
- url 自动补全（OpenAI / Anthropic 双格式）
- 消息转换（system_prompt 优先 / 重复 system 去重）
- analyze_with_structured_output 解析 ```json``` 围栏 / 裸 JSON / 解析失败
- record_call / get_stats / reset_stats / estimate_cost
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tools.llm import LLMClient, LLMMessage, LLMResponse, OpenAICompatibleClient


def _client(tmp_path, **overrides):
    kw = dict(
        api_key="sk-FAKEKEY",
        api_url="https://example.invalid/v1",
        model="agnes-2.0-flash",
        cache_dir=str(tmp_path / "llm_cache"),
    )
    kw.update(overrides)
    return OpenAICompatibleClient(**kw)


# ----- token estimation -----

def test_estimate_tokens_chinese_vs_english(tmp_path):
    c = _client(tmp_path)
    # "你好" → 2 字 * 1.5 = 3
    assert c.estimate_tokens("你好") == 3
    # "hello" → 5 char * 0.25 = 1
    assert c.estimate_tokens("hello") == 1
    assert c.estimate_tokens("") == 0


def test_count_tokens_includes_overhead(tmp_path):
    c = _client(tmp_path)
    msgs = [LLMMessage(role="user", content="hi"), LLMMessage(role="assistant", content="ok")]
    n = c.count_tokens(msgs)
    # 每条消息 +10 开销，hi=0, ok=0 → 20
    assert n == 20


# ----- cache key -----

def test_cache_key_stable_across_calls(tmp_path):
    c = _client(tmp_path)
    msgs = [LLMMessage(role="user", content="hello")]
    k1 = c._get_cache_key(msgs, max_tokens=100, temperature=0.5)
    k2 = c._get_cache_key(msgs, max_tokens=100, temperature=0.5)
    assert k1 == k2
    k3 = c._get_cache_key(msgs, max_tokens=200, temperature=0.5)
    assert k1 != k3


def test_cache_set_and_get_round_trip(tmp_path):
    c = _client(tmp_path)
    resp = LLMResponse(content="x", model="m", tokens_used=1, finish_reason="stop")
    c._set_cache("key1", resp)
    got = c._get_cache("key1")
    assert got is not None and got.content == "x"


def test_cache_miss_returns_none(tmp_path):
    c = _client(tmp_path)
    assert c._get_cache("no-such-key") is None


# ----- URL auto-completion -----

def test_url_auto_complete_openai_v1(tmp_path):
    c = _client(tmp_path, api_url="https://example.invalid/v1")
    assert c.api_url.endswith("/chat/completions")


def test_url_auto_complete_openai_already_complete(tmp_path):
    c = _client(tmp_path, api_url="https://example.invalid/v1/chat/completions")
    assert c.api_url == "https://example.invalid/v1/chat/completions"


def test_url_auto_complete_openai_no_v1(tmp_path):
    c = _client(tmp_path, api_url="https://example.invalid")
    assert c.api_url == "https://example.invalid/v1/chat/completions"


def test_url_auto_complete_anthropic_format(tmp_path):
    c = _client(tmp_path,
                api_url="https://example.invalid/v1",
                use_anthropic_format=True)
    assert c.api_url.endswith("/messages")


# ----- message conversion -----

def test_convert_messages_with_system_prompt(tmp_path):
    c = _client(tmp_path)
    msgs = [LLMMessage(role="user", content="hi")]
    out = c._convert_messages(msgs, system_prompt="be brief")
    assert out[0] == {"role": "system", "content": "be brief"}
    assert out[1] == {"role": "user", "content": "hi"}


def test_convert_messages_strips_duplicate_system(tmp_path):
    c = _client(tmp_path)
    msgs = [
        LLMMessage(role="system", content="first"),
        LLMMessage(role="user", content="hi"),
    ]
    out = c._convert_messages(msgs, system_prompt="explicit")
    # 重复 system 应被跳过
    roles = [m["role"] for m in out]
    assert roles.count("system") == 1
    assert out[0]["content"] == "explicit"


# ----- record_call / stats -----

def test_record_call_and_stats(tmp_path):
    c = _client(tmp_path)
    c.record_call(100)
    c.record_call(200, metadata={"x": 1})
    stats = c.get_stats()
    assert stats["total_calls"] == 2
    assert stats["total_tokens"] == 300
    assert stats["avg_tokens_per_call"] == 150
    assert stats["model"] == "agnes-2.0-flash"


def test_reset_stats_clears_history(tmp_path):
    c = _client(tmp_path)
    c.record_call(50)
    c.reset_stats()
    assert c.get_stats()["total_calls"] == 0
    assert c.get_stats()["total_tokens"] == 0
    assert c.get_stats()["avg_tokens_per_call"] == 0


# ----- estimate_cost -----

def test_estimate_cost_default_pricing(tmp_path):
    c = _client(tmp_path)
    cost = c.estimate_cost(1000)
    # 默认 input 0.0008, output 0.002, 50/50 拆分 → (500/1000)*0.0008 + (500/1000)*0.002 = 0.0014
    assert cost == pytest.approx(0.0014, rel=1e-6)


def test_estimate_cost_custom_pricing(tmp_path):
    c = _client(tmp_path)
    cost = c.estimate_cost(2000, pricing={"input": 0.001, "output": 0.001})
    # 1000 * 0.001 + 1000 * 0.001 / 1000 * 1000... = 1000/1000*0.001 + 1000/1000*0.001 = 0.002
    assert cost == pytest.approx(0.002, rel=1e-6)


# ----- analyze_with_structured_output -----

def _patch_analyze(monkeypatch, client, content):
    async def fake_analyze(messages, max_tokens=4096, temperature=0.7, use_cache=True, system_prompt=None):
        return LLMResponse(content=content, model=client.model, tokens_used=10, finish_reason="stop")
    monkeypatch.setattr(client, "analyze", fake_analyze)


def test_structured_output_pure_json(tmp_path, monkeypatch):
    c = _client(tmp_path)
    _patch_analyze(monkeypatch, c, '{"score": 90, "ok": true}')
    out = asyncio.run(c.analyze_with_structured_output(
        [LLMMessage(role="user", content="rate")],
        output_schema={"score": "int"},
    ))
    assert out == {"score": 90, "ok": True}


def test_structured_output_json_fence(tmp_path, monkeypatch):
    c = _client(tmp_path)
    _patch_analyze(monkeypatch, c, '```json\n{"a": 1}\n```')
    out = asyncio.run(c.analyze_with_structured_output(
        [LLMMessage(role="user", content="rate")],
        output_schema={},
    ))
    assert out == {"a": 1}


def test_structured_output_generic_fence(tmp_path, monkeypatch):
    c = _client(tmp_path)
    _patch_analyze(monkeypatch, c, '```\n{"b": 2}\n```')
    out = asyncio.run(c.analyze_with_structured_output(
        [LLMMessage(role="user", content="rate")],
        output_schema={},
    ))
    assert out == {"b": 2}


def test_structured_output_invalid_json_raises(tmp_path, monkeypatch):
    c = _client(tmp_path)
    _patch_analyze(monkeypatch, c, "not json at all")
    with pytest.raises(ValueError, match="JSON"):
        asyncio.run(c.analyze_with_structured_output(
            [LLMMessage(role="user", content="x")], {},
        ))


# ----- analyze cache hit short-circuit -----

def test_analyze_returns_cached_without_calling_api(tmp_path, monkeypatch):
    c = _client(tmp_path)
    # 准备缓存
    cached = LLMResponse(content="from cache", model=c.model, tokens_used=5, finish_reason="stop")
    monkeypatch.setattr(c, "_get_cache", lambda key: cached)

    async def boom(*a, **kw):
        raise AssertionError("api should not be called")
    monkeypatch.setattr(c, "_call_api", boom)
    # quality_check 写入需要 db；patch 掉避免污染
    monkeypatch.setattr(c, "_record_quality_check", lambda **kw: None)

    out = asyncio.run(c.analyze([LLMMessage(role="user", content="x")], use_cache=True))
    assert out.content == "from cache"


# ----- LLMClient abstract instantiation guard -----

def test_llmclient_is_abstract():
    with pytest.raises(TypeError):
        LLMClient(model="m")  # type: ignore[abstract]
