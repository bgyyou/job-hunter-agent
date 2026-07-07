# -*- coding: utf-8 -*-
"""PR6: rewrite_experience / rewrite_projects 批量 vs per-entry fallback。"""
from __future__ import annotations

import json
import pytest

from agents.resume_flow_a import ResumeFlowA, _BATCH_MAX_INPUT_CHARS


class _FakeResponse:
    def __init__(self, content):
        self.content = content


def _make_flow_a(reply_json_or_text):
    """Mock LLM that returns the given reply verbatim."""

    class _LLM:
        def __init__(self, reply):
            self._reply = reply
            self.calls = 0

        async def analyze(self, messages, max_tokens=1000, temperature=0.2):
            self.calls += 1
            if isinstance(self._reply, str):
                return _FakeResponse(self._reply)
            return _FakeResponse(json.dumps(self._reply, ensure_ascii=False))

    return ResumeFlowA(_LLM(reply_json_or_text))


def _exps(n, total_len=200):
    out = []
    for i in range(n):
        out.append({
            "title": f"Title {i}",
            "company": f"Co {i}",
            "duration": "2020-2022",
            "description": "x" * total_len,
            "achievements": ["did X"],
        })
    return out


@pytest.mark.asyncio
async def test_rewrite_experience_batch_when_list_returns_same_length():
    """LLM 返回 list 且长度匹配时直接用。"""
    exps = _exps(3)
    flow = _make_flow_a([
        {"title": "NewT", "company": "NewC", "duration": "2021-2023",
         "description": "rewritten", "achievements": ["did Y"]},
        {"title": "NewT2", "company": "NewC2", "duration": "2021-2023",
         "description": "rewritten", "achievements": ["did Y"]},
        {"title": "NewT3", "company": "NewC3", "duration": "2021-2023",
         "description": "rewritten", "achievements": ["did Y"]},
    ])
    out = await flow.rewrite_experience(
        {"experience": exps}, "互联网", "AI PM", skeleton_text="",
    )
    assert len(out) == 3
    assert out[0]["title"] == "NewT"
    # 单次 LLM 调用（batch）
    assert flow.llm_client.calls == 1


@pytest.mark.asyncio
async def test_rewrite_experience_batch_falls_back_when_length_mismatch():
    """LLM 返回 list 长度不匹配 → 退 per-entry，每条 1 次调用 = 3 次总。"""
    exps = _exps(3)
    flow = _make_flow_a([
        {"title": "Only One", "description": "ok"},  # 长度 1 ≠ 3 → fallback
    ])
    out = await flow.rewrite_experience(
        {"experience": exps}, "互联网", "AI PM", skeleton_text="",
    )
    # per-entry 退到原 exp
    assert len(out) == 3
    assert out[0]["company"] == "Co 0"
    assert flow.llm_client.calls == 4  # 1 batch + 3 per-entry


@pytest.mark.asyncio
async def test_rewrite_experience_skips_batch_for_huge_input():
    """总 chars > _BATCH_MAX_INPUT_CHARS 直接走 per-entry。"""
    big = _exps(5, total_len=2000)  # 总 ~10000 字符
    flow = _make_flow_a([{"title": "X"}])  # batch 不会执行
    out = await flow.rewrite_experience(
        {"experience": big}, "互联网", "AI PM", skeleton_text="",
    )
    # 5 条都原样返回
    assert len(out) == 5
    assert out[0]["company"] == "Co 0"
    assert flow.llm_client.calls == 5  # batch skipped → 5 per-entry


@pytest.mark.asyncio
async def test_rewrite_experience_skips_batch_for_single_entry():
    """1 条经历 → _skip_batch_for len>1 → 单次 per-entry 调用。"""
    flow = _make_flow_a([{"title": "New", "description": "rewritten"}])
    out = await flow.rewrite_experience(
        {"experience": _exps(1)}, "互联网", "AI PM", skeleton_text="",
    )
    assert len(out) == 1
    assert flow.llm_client.calls == 1


@pytest.mark.asyncio
async def test_rewrite_projects_batch_happy_path():
    projects = [
        {"name": "P1", "role": "PM", "tech_stack": ["LLM"], "description": "y", "achievements": ["did A"]},
        {"name": "P2", "role": "Eng", "tech_stack": ["Py"], "description": "y", "achievements": ["did B"]},
    ]
    flow = _make_flow_a([
        {"name": "P1R", "role": "PM", "tech_stack": ["LLM"], "description": "rewritten", "achievements": ["did A"]},
        {"name": "P2R", "role": "Eng", "tech_stack": ["Py"], "description": "rewritten", "achievements": ["did B"]},
    ])
    out = await flow.rewrite_projects(
        {"projects": projects}, "互联网", "AI PM", skeleton_text="",
    )
    assert len(out) == 2
    assert out[0]["name"] == "P1R"
    assert out[1]["name"] == "P2R"
    assert flow.llm_client.calls == 1


@pytest.mark.asyncio
async def test_rewrite_experience_empty_list_returns_empty():
    flow = _make_flow_a([])
    out = await flow.rewrite_experience({"experience": []}, "互联网", "AI PM", "")
    assert out == []
    assert flow.llm_client.calls == 0


def test_batch_max_input_chars_constant_is_reasonable():
    """至少 2000 字符（确保批量化有意义）且 ≤ 8000（避免过 token 上限）。"""
    assert 2000 <= _BATCH_MAX_INPUT_CHARS <= 8000
