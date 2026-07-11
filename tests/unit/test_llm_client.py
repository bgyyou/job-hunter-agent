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

from tools.llm import LLMClient, LLMMessage, LLMResponse, OpenAICompatibleClient, StreamChunk


def _client(tmp_path, **overrides):
    kw = dict(
        api_key="FAKEKEY",
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
    # llm_calls 写入需要 db；patch 掉避免污染
    monkeypatch.setattr(c, "_record_llm_call", lambda **kw: None)

    out = asyncio.run(c.analyze([LLMMessage(role="user", content="x")], use_cache=True))
    assert out.content == "from cache"


# ----- retry behavior -----


def test_analyze_retries_retryable_api_failure(tmp_path, monkeypatch):
    c = _client(tmp_path)
    c.retry_delays = (0, 0)
    attempts = {"n": 0}

    async def flaky_call(*args, **kwargs):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("API 调用失败 (500): upstream busy")
        return {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 7},
            "model": c.model,
        }

    monkeypatch.setattr(c, "_call_api", flaky_call)
    monkeypatch.setattr(c, "_record_llm_call", lambda **kw: None)

    out = asyncio.run(c.analyze([LLMMessage(role="user", content="x")], use_cache=False))

    assert out.content == "ok"
    assert attempts["n"] == 3


# ----- v2.1 P2-3: thinking model reasoning 吃光预算的非流式兜底 -----

def test_analyze_retries_when_reasoning_starves_content(tmp_path, monkeypatch):
    """thinking model reasoning 吃光 max_tokens → content 空 + finish=length。
    analyze() 必须带 headroom 自动重试一次，并透传 reasoning。"""
    c = _client(tmp_path)
    c.retry_delays = (0, 0)
    calls = []

    async def fake_call(messages, max_tokens, temperature):
        calls.append(max_tokens)
        if len(calls) == 1:
            # 第一次：预算被 reasoning 吃光，content 空，被 length 截断
            return {
                "choices": [{
                    "message": {"content": "", "reasoning_content": "想" * 500},
                    "finish_reason": "length",
                }],
                "usage": {"total_tokens": 1000},
                "model": c.model,
            }
        # 重试（更大预算）：正常吐出答案
        return {
            "choices": [{
                "message": {"content": '{"ok": true}', "reasoning_content": "想" * 500},
                "finish_reason": "stop",
            }],
            "usage": {"total_tokens": 2500},
            "model": c.model,
        }

    monkeypatch.setattr(c, "_call_api", fake_call)
    monkeypatch.setattr(c, "_record_llm_call", lambda **kw: None)

    out = asyncio.run(c.analyze([LLMMessage(role="user", content="x")], max_tokens=1000, use_cache=False))

    assert out.content == '{"ok": true}'
    assert out.reasoning  # reasoning 被透传
    assert len(calls) == 2  # 触发了一次兜底重试
    assert calls[1] > calls[0]  # 重试预算更大


def test_analyze_no_retry_when_content_present(tmp_path, monkeypatch):
    """content 正常返回时不应触发兜底重试（避免误伤 + 额外成本）。"""
    c = _client(tmp_path)
    calls = []

    async def fake_call(messages, max_tokens, temperature):
        calls.append(max_tokens)
        return {
            "choices": [{
                "message": {"content": "hello", "reasoning_content": "想"},
                "finish_reason": "stop",
            }],
            "usage": {"total_tokens": 10},
            "model": c.model,
        }

    monkeypatch.setattr(c, "_call_api", fake_call)
    monkeypatch.setattr(c, "_record_llm_call", lambda **kw: None)

    out = asyncio.run(c.analyze([LLMMessage(role="user", content="x")], max_tokens=1000, use_cache=False))

    assert out.content == "hello"
    assert len(calls) == 1  # 没有重试


def test_analyze_no_retry_on_legit_empty_without_reasoning(tmp_path, monkeypatch):
    """content 空但 finish=stop 且无 reasoning → 是正常空响应，不重试。"""
    c = _client(tmp_path)
    calls = []

    async def fake_call(messages, max_tokens, temperature):
        calls.append(max_tokens)
        return {
            "choices": [{
                "message": {"content": "", "reasoning_content": ""},
                "finish_reason": "stop",
            }],
            "usage": {"total_tokens": 5},
            "model": c.model,
        }

    monkeypatch.setattr(c, "_call_api", fake_call)
    monkeypatch.setattr(c, "_record_llm_call", lambda **kw: None)

    out = asyncio.run(c.analyze([LLMMessage(role="user", content="x")], max_tokens=1000, use_cache=False))

    assert out.content == ""
    assert len(calls) == 1  # 不重试


# ----- LLMClient abstract instantiation guard -----

def test_llmclient_is_abstract():
    with pytest.raises(TypeError):
        LLMClient(model="m")  # type: ignore[abstract]


# ----- v2.1 P2-2: thinking model reasoning_content 解析 -----

def test_stream_chunk_default_has_optional_reasoning():
    """StreamChunk 默认 reasoning_content=None，向后兼容老调用方。"""
    chunk = StreamChunk(content="hello")
    assert chunk.content == "hello"
    assert chunk.reasoning_content is None
    assert chunk.is_complete is False

    # 显式传空串 reasoning 也 OK（None 或 '' 都被视为"无思考过程"）
    chunk2 = StreamChunk(content="x", reasoning_content="")
    assert chunk2.reasoning_content == ""


def test_analyze_stream_yields_reasoning_and_content_separately(tmp_path, monkeypatch):
    """thinking model 的 SSE 流同时含 content 和 reasoning_content，
    analyze_stream 必须分别透传到 StreamChunk，不能丢弃 reasoning。"""
    c = _client(tmp_path)

    async def fake_stream(messages, max_tokens, temperature):
        # 模拟 thinking model 的 chunk 序列：
        # 先吐 reasoning，然后吐 content，最后 [DONE]
        yield {"reasoning_content": "用户问开始采集"}
        yield {"reasoning_content": "工作经历"}
        yield {"content": "好的，"}
        yield {"reasoning_content": "先问公司名", "content": "请告诉"}
        yield {"content": "我您最近一份工作的公司名？"}
        # content 已结束但 reasoning 还会继续（截断情形）
        yield {"reasoning_content": "考虑是否要给个示例"}

    monkeypatch.setattr(c, "_call_api_stream", fake_stream)
    monkeypatch.setattr(c, "record_call", lambda *a, **kw: None)

    chunks = asyncio.run(_drain_stream(c.analyze_stream(
        [LLMMessage(role="user", content="开始采集")],
        max_tokens=2048,
        temperature=0.6,
    )))

    # 收齐所有 chunk（含 is_complete=True 的 sentinel）
    contents = [ch.content for ch in chunks if ch.content]
    reasonings = [ch.reasoning_content for ch in chunks if ch.reasoning_content]
    assert "".join(contents) == "好的，请告诉我您最近一份工作的公司名？"
    assert "".join(reasonings) == "用户问开始采集工作经历先问公司名考虑是否要给个示例"

    # 最后一定有 is_complete=True 的 chunk
    assert chunks[-1].is_complete is True


def test_analyze_stream_skips_empty_chunks_without_crashing(tmp_path, monkeypatch):
    """上游偶尔会发 delta 里 content/reasoning_content 都为空（如 role-only chunk），
    这种 chunk 应该被安静跳过，不应该 yield 出空 StreamChunk。"""
    c = _client(tmp_path)

    async def fake_stream(messages, max_tokens, temperature):
        yield {"role": "assistant", "content": "", "reasoning_content": ""}
        yield {"content": "实际内容"}
        yield {"reasoning_content": ""}  # 空字符串 reasoning
        yield {}

    monkeypatch.setattr(c, "_call_api_stream", fake_stream)
    monkeypatch.setattr(c, "record_call", lambda *a, **kw: None)

    chunks = asyncio.run(_drain_stream(c.analyze_stream(
        [LLMMessage(role="user", content="x")], max_tokens=2048, temperature=0.6,
    )))

    # 仅收到有 content 的 chunk + 收尾 sentinel
    real_chunks = [ch for ch in chunks if not ch.is_complete]
    assert len(real_chunks) == 1
    assert real_chunks[0].content == "实际内容"
    assert real_chunks[0].reasoning_content is None  # 空串被规范化为 None


def test_analyze_stream_reasoning_only_then_content_truncated(tmp_path, monkeypatch):
    """thinking model 的常见故障模式：reasoning 吃光 token，content 被截断为空。

    v2.1 P3-B: analyze_stream 必须自动用更大 budget 重试一次（对齐 analyze() 的
    _retry_if_reasoning_starved），最后让 caller 拿到真实 content，而不是空字符串。
    """
    c = _client(tmp_path)

    call_count = {"n": 0}

    async def fake_stream(messages, max_tokens, temperature):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # 第一次：50 个 reasoning chunk + 0 content（reasoning 吃光预算）
            for i in range(50):
                yield {"reasoning_content": f"思考第 {i} 步 "}
            return
        # 第二次：更大 budget 下产出真实 content
        for i in range(3):
            yield {"reasoning_content": f"重试思考 {i} "}
        yield {"content": "重试后真实答案"}

    monkeypatch.setattr(c, "_call_api_stream", fake_stream)
    monkeypatch.setattr(c, "record_call", lambda *a, **kw: None)

    chunks = asyncio.run(_drain_stream(c.analyze_stream(
        [LLMMessage(role="user", content="x")], max_tokens=600, temperature=0.6,
    )))

    # 至少调用了两次（首轮 + 重试）
    assert call_count["n"] >= 2, "should auto-retry when reasoning starves content"
    # 两次 reasoning chunk 都透传了
    reasonings = [ch.reasoning_content for ch in chunks if ch.reasoning_content]
    assert len(reasonings) == 53  # 50 + 3
    # 重试后 content 真的出现了
    contents = [ch.content for ch in chunks if ch.content]
    assert contents == ["重试后真实答案"]
    # 收尾 sentinel 仍然存在
    assert chunks[-1].is_complete is True


def test_analyze_stream_no_retry_when_content_present(tmp_path, monkeypatch):
    """v2.1 P3-B 边界：首轮就拿到 content 时，不应该触发 reasoning-starved 重试。"""
    c = _client(tmp_path)
    call_count = {"n": 0}

    async def fake_stream(messages, max_tokens, temperature):
        call_count["n"] += 1
        yield {"content": "直接回答"}

    monkeypatch.setattr(c, "_call_api_stream", fake_stream)
    monkeypatch.setattr(c, "record_call", lambda *a, **kw: None)

    chunks = asyncio.run(_drain_stream(c.analyze_stream(
        [LLMMessage(role="user", content="x")], max_tokens=600, temperature=0.6,
    )))

    assert call_count["n"] == 1, "no retry when content arrives normally"
    assert chunks[-1].is_complete is True


def test_analyze_stream_no_retry_when_neither_reasoning_nor_content(tmp_path, monkeypatch):
    """v2.1 P3-B 边界：首轮连 reasoning 都没有（纯空流），也不重试 — 模型本就该返空。"""
    c = _client(tmp_path)
    call_count = {"n": 0}

    async def fake_stream(messages, max_tokens, temperature):
        call_count["n"] += 1
        # 完全空的流（不 yield 任何 chunk）
        if False:
            yield {}

    monkeypatch.setattr(c, "_call_api_stream", fake_stream)
    monkeypatch.setattr(c, "record_call", lambda *a, **kw: None)

    chunks = asyncio.run(_drain_stream(c.analyze_stream(
        [LLMMessage(role="user", content="x")], max_tokens=600, temperature=0.6,
    )))

    assert call_count["n"] == 1, "no retry when stream is naturally empty"
    assert chunks[-1].is_complete is True


async def _drain_stream(async_gen):
    """把 async generator 跑完收集到 list。"""
    out = []
    async for ch in async_gen:
        out.append(ch)
    return out
