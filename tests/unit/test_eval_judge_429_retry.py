"""[M-v4-1 judge 限流] Unit tests for eval/judge.py retry + concurrency policy.

覆盖目标：
- mock 429 响应 → 验证 retry 逻辑生效（指数退避 / 次数受 env 控制）
- mock 持续 429 → 验证 fallback 到 mock_judge 不抛异常 + raw_response 标 429_RATE_LIMIT
- mock 成功响应 → 验证不重试（只调一次 LLM）
- mock 非 429 错误 → 仅 1 次重试就 fallback
- backoff 间隔符合预期（base * 2^attempt）
- LLM_JUDGE_CONCURRENCY 环境变量控制默认并发
- _is_rate_limit_error 正确识别 429 / rate limit / too many requests
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from eval.judge import (  # noqa: E402
    JudgeVerdict,
    LLMJudge,
    _is_rate_limit_error,
    _get_retry_config,
    _get_default_concurrency,
    _mock_judge,
    judge_batch_per_query,
)


# ---- helpers ---------------------------------------------------------------

class _FakeResponse:
    def __init__(self, content: str):
        self.content = content


def _make_judge(monkeypatch, calls: list, raises: list[Exception] | None = None):
    """Create LLMJudge with a fake client.analyze that records calls and raises per index.

    raises[i] = exception to raise on i-th call (None = return fake success)

    Strategy: monkeypatch the module-level `from tools.llm import LLMMessage` symbol
    so `_judge_query_batch` / `judge` see a fake module attribute, then patch the
    fake client's analyze method.
    """
    if raises is None:
        raises = []

    class _FakeClient:
        def __init__(self):
            self.analyze_calls = calls

        async def analyze(self, messages, max_tokens=10, temperature=0.0, use_cache=True, **kw):
            calls.append({"messages": messages, "max_tokens": max_tokens})
            idx = len(calls) - 1
            if idx < len(raises) and raises[idx] is not None:
                raise raises[idx]
            return _FakeResponse("[3, 4, 5]")

    fake_client = _FakeClient()

    # Inject a fake `tools.llm` module so `from tools.llm import LLMMessage, OpenAICompatibleClient`
    # inside judge.py resolves to our fake types.
    import types
    fake_llm = types.ModuleType("tools.llm")

    class _FakeLLMMessage:
        def __init__(self, role, content, metadata=None):
            self.role = role
            self.content = content

    class _FakeOpenAICompatibleClient:
        def __init__(self, *args, **kwargs):
            self._fake_client = fake_client

    fake_llm.LLMMessage = _FakeLLMMessage
    fake_llm.OpenAICompatibleClient = _FakeOpenAICompatibleClient

    import sys as _sys
    monkeypatch.setitem(_sys.modules, "tools.llm", fake_llm)

    judge = LLMJudge()
    monkeypatch.setattr(judge, "is_available", True)
    monkeypatch.setattr(judge, "_client", fake_client)
    monkeypatch.setattr(judge, "_get_client", lambda: fake_client)
    monkeypatch.setattr(judge, "api_key", "fake")
    monkeypatch.setattr(judge, "base_url", "https://example.invalid")

    return judge


@pytest.fixture
def fast_sleep(monkeypatch):
    """Replace asyncio.sleep with a no-op so tests run instantly."""
    sleeps: list[float] = []
    async def _sleep(s):
        sleeps.append(s)
    monkeypatch.setattr(asyncio, "sleep", _sleep)
    return sleeps


# ---- _is_rate_limit_error --------------------------------------------------

class TestIsRateLimit:
    def test_429_keyword(self):
        assert _is_rate_limit_error(Exception("API 调用失败 (429): rate limit")) is True

    def test_rate_limit_keyword(self):
        assert _is_rate_limit_error(Exception("upstream rate limit exceeded")) is True

    def test_too_many_requests(self):
        assert _is_rate_limit_error(Exception("429 Too Many Requests")) is True

    def test_unrelated_error(self):
        assert _is_rate_limit_error(Exception("timeout reading socket")) is False

    def test_500_is_not_rate_limit(self):
        # 500 不算 429（OpenAICompatibleClient._is_retryable_exception 会 retry，但本 helper 只盯 429）
        assert _is_rate_limit_error(Exception("API 调用失败 (500): internal")) is False


# ---- _get_retry_config / _get_default_concurrency --------------------------

class TestRetryConfig:
    def test_defaults(self, monkeypatch):
        monkeypatch.delenv("JUDGE_MAX_RETRIES", raising=False)
        monkeypatch.delenv("JUDGE_RETRY_BASE_DELAY", raising=False)
        n, base = _get_retry_config()
        assert n == 5
        assert base == 1.0

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("JUDGE_MAX_RETRIES", "7")
        monkeypatch.setenv("JUDGE_RETRY_BASE_DELAY", "0.5")
        n, base = _get_retry_config()
        assert n == 7
        assert base == 0.5

    def test_invalid_env_falls_back(self, monkeypatch):
        monkeypatch.setenv("JUDGE_MAX_RETRIES", "not-a-number")
        monkeypatch.setenv("JUDGE_RETRY_BASE_DELAY", "garbage")
        n, base = _get_retry_config()
        assert n == 5
        assert base == 1.0

    def test_negative_clamped(self, monkeypatch):
        monkeypatch.setenv("JUDGE_MAX_RETRIES", "-3")
        monkeypatch.setenv("JUDGE_RETRY_BASE_DELAY", "-1.0")
        n, base = _get_retry_config()
        assert n == 0
        assert base == 0.0


class TestDefaultConcurrency:
    def test_default_is_one(self, monkeypatch):
        monkeypatch.delenv("LLM_JUDGE_CONCURRENCY", raising=False)
        assert _get_default_concurrency() == 1

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("LLM_JUDGE_CONCURRENCY", "4")
        assert _get_default_concurrency() == 4

    def test_zero_clamped_to_one(self, monkeypatch):
        monkeypatch.setenv("LLM_JUDGE_CONCURRENCY", "0")
        assert _get_default_concurrency() == 1

    def test_negative_clamped_to_one(self, monkeypatch):
        monkeypatch.setenv("LLM_JUDGE_CONCURRENCY", "-5")
        assert _get_default_concurrency() == 1

    def test_invalid_falls_back_to_one(self, monkeypatch):
        monkeypatch.setenv("LLM_JUDGE_CONCURRENCY", "abc")
        assert _get_default_concurrency() == 1


# ---- judge_batch_query: retry semantics ------------------------------------

class TestJudgeBatch429Retry:
    async def test_429_then_success_retries(self, monkeypatch, fast_sleep):
        """mock 一次 429 → 第二次成功 → 应返回真 judge 结果（不 mock fallback）。"""
        calls = []
        raises = [Exception("API 调用失败 (429): rate limit"), None]
        judge = _make_judge(monkeypatch, calls, raises)

        query = {"query_id": "q1", "query": "Python 数据"}
        cands = [
            {"jd_id": "a", "title": "Data Analyst", "text": "Python SQL"},
            {"jd_id": "b", "title": "Driver", "text": "License"},
        ]
        verdicts = await judge._judge_query_batch(query, cands)

        assert len(verdicts) == 2
        assert all(not v.is_mock for v in verdicts), "成功路径不应 fallback"
        assert len(calls) == 2, "应调 2 次 LLM（1 次 429 + 1 次成功）"
        # backoff 序列：1.0 * 2^0 = 1.0
        assert fast_sleep == [1.0]

    async def test_continuous_429_falls_back_to_mock(self, monkeypatch, fast_sleep):
        """mock 持续 5 次 429 → 第 6 次仍失败 → fallback 到 mock，raw_response 含 429_RATE_LIMIT。"""
        calls = []
        raises = [Exception("API 调用失败 (429): rate limit")] * 10
        judge = _make_judge(monkeypatch, calls, raises)

        query = {"query_id": "q1", "query": "Python 数据"}
        cands = [{"jd_id": "a", "title": "Data Analyst", "text": "Python"}]
        verdicts = await judge._judge_query_batch(query, cands)

        assert len(verdicts) == 1
        v = verdicts[0]
        assert v.is_mock is True, "全 retry 失败应 fallback"
        assert "429_RATE_LIMIT" in v.raw_response
        # 默认 5 次 429 retry + 1 次最终尝试 = 6 次调用
        assert len(calls) == 6
        # backoff 序列：1.0 * 2^0/1/2/3/4 = 1.0/2.0/4.0/8.0/16.0
        assert fast_sleep == [1.0, 2.0, 4.0, 8.0, 16.0]

    async def test_no_retry_on_success(self, monkeypatch, fast_sleep):
        """mock 一次成功 → 不应重试，只调 1 次 LLM。"""
        calls = []
        raises = []
        judge = _make_judge(monkeypatch, calls, raises)

        query = {"query_id": "q1", "query": "Python 数据"}
        cands = [{"jd_id": "a", "title": "Data Analyst", "text": "Python"}]
        verdicts = await judge._judge_query_batch(query, cands)

        assert len(verdicts) == 1
        assert verdicts[0].is_mock is False
        assert len(calls) == 1, "成功路径不应 retry"
        assert fast_sleep == []

    async def test_non_429_only_one_retry(self, monkeypatch, fast_sleep):
        """mock 持续非 429 错误（如 timeout）→ 只 retry 1 次就 fallback。"""
        calls = []
        raises = [Exception("timeout reading socket")] * 10
        judge = _make_judge(monkeypatch, calls, raises)

        query = {"query_id": "q1", "query": "Python 数据"}
        cands = [{"jd_id": "a", "title": "Data Analyst", "text": "Python"}]
        verdicts = await judge._judge_query_batch(query, cands)

        assert verdicts[0].is_mock is True
        assert "OTHER_ERROR" in verdicts[0].raw_response
        # 1 次原始 + 1 次重试 = 2 次调用
        assert len(calls) == 2
        assert fast_sleep == [0.5]

    async def test_429_max_retries_configurable(self, monkeypatch, fast_sleep):
        """JUDGE_MAX_RETRIES=2 → 持续 429 时只 retry 2 次就 fallback。"""
        calls = []
        raises = [Exception("API 调用失败 (429): rate limit")] * 10
        judge = _make_judge(monkeypatch, calls, raises)
        monkeypatch.setenv("JUDGE_MAX_RETRIES", "2")

        query = {"query_id": "q1", "query": "Python"}
        cands = [{"jd_id": "a", "title": "T", "text": "x"}]
        verdicts = await judge._judge_query_batch(query, cands)

        assert verdicts[0].is_mock is True
        # 2 次 retry + 1 次最终尝试 = 3 次调用
        assert len(calls) == 3
        assert fast_sleep == [1.0, 2.0]

    async def test_429_base_delay_configurable(self, monkeypatch, fast_sleep):
        """JUDGE_RETRY_BASE_DELAY=0.25 → backoff 序列 0.25/0.5/1.0/2.0/4.0。"""
        calls = []
        raises = [Exception("API 调用失败 (429): rate limit")] * 10
        judge = _make_judge(monkeypatch, calls, raises)
        monkeypatch.setenv("JUDGE_RETRY_BASE_DELAY", "0.25")

        query = {"query_id": "q1", "query": "Python"}
        cands = [{"jd_id": "a", "title": "T", "text": "x"}]
        await judge._judge_query_batch(query, cands)

        assert fast_sleep == [0.25, 0.5, 1.0, 2.0, 4.0]


# ---- judge_batch_per_query: concurrency ------------------------------------

class TestJudgeBatchConcurrency:
    async def test_default_concurrency_is_one(self, monkeypatch, fast_sleep):
        """未传 concurrency 且无 env 时，并发应为 1。"""
        calls = []
        raises = []
        judge = _make_judge(monkeypatch, calls, raises)

        queries = [
            {"query_id": "q1", "query": "Python"},
            {"query_id": "q2", "query": "Driver"},
        ]
        cands = [[{"jd_id": "a", "title": "T", "text": "x"}]] * 2

        # Capture semaphore concurrency by patching asyncio.Semaphore
        sem_values = []
        original_semaphore = asyncio.Semaphore
        def _capturing_semaphore(value):
            sem_values.append(value)
            return original_semaphore(value)
        monkeypatch.setattr(asyncio, "Semaphore", _capturing_semaphore)

        results = await judge_batch_per_query(queries, cands)
        assert len(results) == 2
        assert sem_values == [1], f"期望默认并发=1, 实际 {sem_values}"

    async def test_env_concurrency(self, monkeypatch, fast_sleep):
        """LLM_JUDGE_CONCURRENCY=3 → 并发=3。"""
        monkeypatch.setenv("LLM_JUDGE_CONCURRENCY", "3")

        calls = []
        raises = []
        judge = _make_judge(monkeypatch, calls, raises)

        sem_values = []
        original_semaphore = asyncio.Semaphore
        def _capturing_semaphore(value):
            sem_values.append(value)
            return original_semaphore(value)
        monkeypatch.setattr(asyncio, "Semaphore", _capturing_semaphore)

        queries = [{"query_id": "q1", "query": "Python"}]
        cands = [[{"jd_id": "a", "title": "T", "text": "x"}]]
        results = await judge_batch_per_query(queries, cands)
        assert len(results) == 1
        assert sem_values == [3]


# ---- judge (single): retry semantics ---------------------------------------

class TestJudgeSingle429Retry:
    async def test_continuous_429_falls_back(self, monkeypatch, fast_sleep):
        """单条 judge：持续 429 → mock fallback。"""
        calls = []
        raises = [Exception("API 调用失败 (429): rate limit")] * 10
        judge = _make_judge(monkeypatch, calls, raises)

        v = await judge.judge("Python 数据", "jd1", "Data Analyst", "Python SQL")

        assert v.is_mock is True
        assert "429_RATE_LIMIT" in v.raw_response
        assert len(calls) == 6
        assert fast_sleep == [1.0, 2.0, 4.0, 8.0, 16.0]