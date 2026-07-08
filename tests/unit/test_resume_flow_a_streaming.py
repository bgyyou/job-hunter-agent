# -*- coding: utf-8 -*-
"""ResumeFlowA 流式回调契约测试 (v2.1 P2-1 阶段一)

覆盖：
- build_skeleton / derive_summary 在提供 stream_callback 时调 analyze_stream
- 不提供时维持原 analyze 行为
- generate_resume_payload 透传 callback,且 rewrite_callback 收尾触发
- 异常路径下 callback 不抛 / 不阻断
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List

import pytest

from agents.resume_flow_a import ResumeFlowA
from tools.llm import LLMResponse, StreamChunk


# --------------------- mock LLM ---------------------

class _StreamLLM:
    """支持 analyze + analyze_stream 的 mock client。"""

    def __init__(
        self,
        full_text: str,
        chunk_size: int = 5,
        stream_calls: List[str] = None,
        analyze_calls: List[str] = None,
    ) -> None:
        self.full_text = full_text
        self.chunk_size = chunk_size
        self.stream_calls = stream_calls if stream_calls is not None else []
        self.analyze_calls = analyze_calls if analyze_calls is not None else []

    async def analyze(self, messages, **kwargs) -> LLMResponse:
        # 取 user 消息正文 — 仅记录，不消费
        try:
            user_content = next(
                m.content for m in messages if getattr(m, "role", "") == "user"
            )
        except StopIteration:
            user_content = "<no-user-msg>"
        self.analyze_calls.append(user_content[:60])
        return LLMResponse(
            content=self.full_text,
            model="mock",
            tokens_used=10,
            finish_reason="stop",
        )

    async def analyze_stream(self, messages, **kwargs):
        try:
            user_content = next(
                m.content for m in messages if getattr(m, "role", "") == "user"
            )
        except StopIteration:
            user_content = "<no-user-msg>"
        self.stream_calls.append(user_content[:60])
        s = self.full_text
        for i in range(0, len(s), self.chunk_size):
            yield StreamChunk(content=s[i:i + self.chunk_size], is_complete=False)
        yield StreamChunk(content="", is_complete=True)

    async def analyze_with_structured_output(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _patch_rag_with_chunks(flow: ResumeFlowA, n_chunks: int = 3) -> list:
    """给 flow 注入 n 个 fake RAG chunks，让 build_skeleton 进入 LLM 分支。

    返回 chunks 供断言使用。
    """
    chunks = [
        {
            "chunk_text": f"这是第 {i + 1} 条 JD 要求片段 — 需要具备相关能力维度。",
            "chunk_type": "requirement",
            "jd_id": f"jd-{i + 1}",
            "metadata": {"jd_platform": "51job", "jd_industry_tag": "互联网"},
            "similarity": 0.8 - i * 0.05,
        }
        for i in range(n_chunks)
    ]
    flow._retrieve_rag_chunks = lambda position, industry, top_k: chunks
    return chunks


# --------------------- build_skeleton ---------------------

def test_build_skeleton_with_callback_uses_stream():
    """传 stream_callback → 走 analyze_stream 路径。"""
    llm = _StreamLLM(full_text="1. 沟通\n2. 数据\n3. 决策\n")
    flow = ResumeFlowA(llm)
    _patch_rag_with_chunks(flow)

    chunks_received: List[str] = []
    acc_seen: List[str] = []

    def cb(delta: str, accumulated: str) -> None:
        chunks_received.append(delta)
        acc_seen.append(accumulated)

    skeleton = _run(flow.build_skeleton(
        "AI产品经理", "互联网/软件", stream_callback=cb,
    ))

    assert llm.stream_calls, "analyze_stream 应当被调用"
    assert not llm.analyze_calls, "analyze 不应被调（流式路径）"
    # 累计应该单调增长
    assert acc_seen[-1] == "1. 沟通\n2. 数据\n3. 决策\n"
    # 至少一段 delta（不是空字符串）
    assert any(c for c in chunks_received)
    assert skeleton["source"] == "rag"
    assert "1. 沟通" in skeleton["text"] and "3. 决策" in skeleton["text"]  # strip 后无尾换行


def test_build_skeleton_without_callback_uses_analyze():
    """不传 stream_callback → 走原 analyze 路径（向后兼容）。"""
    llm = _StreamLLM(full_text="1. 沟通\n2. 数据\n3. 决策\n")
    flow = ResumeFlowA(llm)
    _patch_rag_with_chunks(flow)

    skeleton = _run(flow.build_skeleton("AI产品经理", "互联网/软件"))

    assert llm.analyze_calls, "analyze 应当被调用"
    assert not llm.stream_calls, "没传 callback 不应调 stream"
    assert "1. 沟通" in skeleton["text"] and "3. 决策" in skeleton["text"]  # strip 后无尾换行


def test_build_skeleton_callback_exception_doesnt_blow_up():
    """callback 抛异常不应阻断主流程 — 用 debug swallow 兜住。"""
    llm = _StreamLLM(full_text="ok 文本")
    flow = ResumeFlowA(llm)
    _patch_rag_with_chunks(flow)

    def bad_cb(d, a):
        raise RuntimeError("ui closed")

    # 不抛
    skeleton = _run(flow.build_skeleton(
        "AI产品经理", "互联网/软件", stream_callback=bad_cb,
    ))
    assert skeleton["text"] == "ok 文本"  # callback 失败但 LLM 流式输出仍捕获


# --------------------- derive_summary ---------------------

@pytest.mark.asyncio
async def test_derive_summary_with_callback_uses_stream():
    """stream_callback 传入 → analyze_stream 路径，文本按 JSON 解析回填。"""
    full = '{"summary": "5 年 AI PM。", "core_competencies": ["RAG", "LLM"]}'
    llm = _StreamLLM(full_text=full)
    flow = ResumeFlowA(llm)

    received: List[str] = []
    derived = await flow.derive_summary_and_competencies(
        collected={"experience": [], "projects": []},
        industry="互联网/软件",
        position="AI产品经理",
        skeleton_text="abc",
        stream_callback=lambda d, a: received.append(d),
    )

    assert llm.stream_calls and not llm.analyze_calls
    assert derived["summary"] == "5 年 AI PM。"
    assert derived["core_competencies"] == ["RAG", "LLM"]


@pytest.mark.asyncio
async def test_derive_summary_without_callback_uses_analyze():
    """向后兼容：不传 callback 走 analyze。"""
    full = '{"summary": "x", "core_competencies": []}'
    llm = _StreamLLM(full_text=full)
    flow = ResumeFlowA(llm)

    derived = await flow.derive_summary_and_competencies(
        collected={"experience": [], "projects": []},
        industry="互联网/软件",
        position="AI产品经理",
    )
    assert llm.analyze_calls and not llm.stream_calls
    assert derived["summary"] == "x"


# --------------------- generate_resume_payload ---------------------

@pytest.mark.asyncio
async def test_generate_payload_passes_callbacks():
    """三个 callback 都应被使用 / 至少被触发。"""
    skeleton_text = "1. 沟通协同\n2. 数据驱动\n3. 决策力\n4. 学习\n5. 文档\n"
    derive_full = '{"summary":"3 年 SaaS。", "core_competencies":["A","B"]}'
    rewrite_experience_full = json.dumps([
        {"title": "PM", "company": "X", "duration": "2023-2024",
         "description": "做了 RAG", "achievements": ["召回提升 35%"]}
    ])
    rewrite_projects_full = json.dumps([
        {"name": "P1", "role": "owner", "tech_stack": ["Python"],
         "description": "做了 llm evals", "achievements": ["-"]}
    ])

    llm = _StreamLLM(full_text=skeleton_text)
    call_n = {"n": 0}
    contents = [skeleton_text, rewrite_experience_full, rewrite_projects_full, derive_full]

    async def analyze(messages, **kw):
        idx = call_n["n"]
        call_n["n"] += 1
        return LLMResponse(content=contents[min(idx, len(contents) - 1)],
                           model="m", tokens_used=10, finish_reason="stop")

    async def analyze_stream(messages, **kw):
        idx = call_n["n"]
        call_n["n"] += 1
        text = contents[min(idx, len(contents) - 1)]
        for i in range(0, len(text), 5):
            yield StreamChunk(content=text[i:i + 5], is_complete=False)
        yield StreamChunk(content="", is_complete=True)

    llm.analyze = analyze
    llm.analyze_stream = analyze_stream

    flow = ResumeFlowA(llm, db=None)
    _patch_rag_with_chunks(flow)

    sk_calls: List[str] = []
    de_calls: List[str] = []
    rw_events: List[tuple] = []

    payload = await flow.generate_resume_payload(
        collected={
            "header": {"name": "Test", "contact": {}},
            "education": [],
            "experience": [{"title": "PM", "company": "X", "duration": "2023-2024",
                            "description": "做了 RAG", "achievements": ["召回提升 35%"]}],
            "projects": [{"name": "P1", "role": "owner", "tech_stack": ["Python"],
                          "description": "llm evals", "achievements": ["-"]}],
            "skills": {"skills": ["Python"]},
            "languages": {"languages": [{"name": "EN", "level": "CET-6"}]},
        },
        industry="互联网/软件",
        position="AI产品经理",
        skeleton_callback=lambda d, a: sk_calls.append(a),
        derive_callback=lambda d, a: de_calls.append(a),
        rewrite_callback=lambda s, p: rw_events.append((s, p)),
    )

    # build_skeleton + derive_summary 都走了流式（提供了 callback）
    assert sk_calls, "skeleton_callback 应当被触发至少一次"
    assert de_calls, "derive_callback 应当被触发至少一次"
    # rewrite_callback 收尾两次（experience + projects）
    stages = {e[0] for e in rw_events}
    assert "experience" in stages
    assert "projects" in stages
    # 返回结构完整
    assert "resume" in payload
    assert "skeleton" in payload
    # summary 来自 derive,应该已回填
    assert payload["resume"]["summary"] == "3 年 SaaS。"
