# -*- coding: utf-8 -*-
"""Flow A 草稿持久化与确定性状态机测试。

这些测试锁住本轮 root fix 的核心原则：
- 草稿状态必须落 SQLite，刷新后可恢复；
- section 是否完成由本地 validator 决定，不由 LLM 文本标记决定；
- 生成阶段可以复用已完成 stage，失败重试不从头来。
"""
from __future__ import annotations

import copy

import pytest

from agents.resume_flow_a import ResumeFlowA
from services.flow_a_draft_service import (
    FlowADraftService,
    missing_fields_label,
    validate_section_completion,
)


# -------------------- draft persistence --------------------


def test_flow_a_draft_round_trip_and_latest(tmp_db):
    service = FlowADraftService(tmp_db, user_id="u1")

    draft_id = service.upsert_draft({
        "industry": "互联网/软件",
        "function": "产品",
        "position": "AI产品经理",
        "current_step": "collect",
        "current_section": "experience",
        "section_data": {"header": {"name": "Leon"}},
        "section_messages": {"experience": [{"role": "user", "content": "开始"}]},
        "section_status": {"experience": "in_progress"},
        "generation_state": {"skeleton": {"status": "pending"}},
    })

    got = service.get_draft(draft_id)
    assert got is not None
    assert got["id"] == draft_id
    assert got["position"] == "AI产品经理"
    assert got["section_data"]["header"]["name"] == "Leon"
    assert got["section_messages"]["experience"][0]["content"] == "开始"
    assert got["generation_state"]["skeleton"]["status"] == "pending"

    service.upsert_draft({
        "id": draft_id,
        "status": "failed",
        "current_step": "generate",
        "last_error": "timeout",
        "generation_state": {"skeleton": {"status": "done", "result": {"text": "x"}}},
    })

    latest = service.get_latest_recoverable_draft()
    assert latest is not None
    assert latest["id"] == draft_id
    assert latest["status"] == "failed"
    assert latest["last_error"] == "timeout"
    assert latest["generation_state"]["skeleton"]["result"]["text"] == "x"

    service.abandon_draft(draft_id)
    assert service.get_latest_recoverable_draft() is None


# -------------------- deterministic validator --------------------


def test_validate_experience_requires_real_fields():
    result = validate_section_completion("experience", [{
        "company": "ACME",
        "title": "产品经理",
        "duration": "2022-2024",
        "achievements": [],
    }])

    assert result.complete is False
    assert "第 1 段工作经历：至少 1 个成果" in result.missing_fields
    assert "成果" in missing_fields_label(result.missing_fields)


def test_validate_experience_complete():
    result = validate_section_completion("experience", [{
        "company": "ACME",
        "title": "产品经理",
        "duration": "2022-2024",
        "achievements": ["转化率提升 20%"],
    }])

    assert result.complete is True
    assert result.missing_fields == []


def test_validate_projects_requires_each_item_fields():
    result = validate_section_completion("projects", [
        {
            "name": "智能客服系统",
            "role": "产品负责人",
            "tech_stack": ["LLM"],
            "description": "搭建 FAQ + RAG",
            "achievements": ["响应时长下降 30%"],
        },
        {
            "name": "数据看板",
            "role": "PM",
            "tech_stack": [],
            "description": "",
            "achievements": [],
        },
    ])

    assert result.complete is False
    assert "第 2 个项目：技术栈" in result.missing_fields
    assert "第 2 个项目：做了什么" in result.missing_fields
    assert "第 2 个项目：主要成果" in result.missing_fields


# -------------------- resumable generation --------------------


@pytest.mark.asyncio
async def test_generate_resume_payload_resumable_skips_done_stages(monkeypatch):
    flow = ResumeFlowA(llm_client=object(), db=None)
    calls: list[str] = []

    async def build_skeleton(position, industry, stream_callback=None):
        calls.append("skeleton")
        return {"text": "fresh skeleton", "source": "rag", "n_chunks": 1}

    async def rewrite_experience(collected, industry, position, skeleton_text=""):
        calls.append("experience")
        return [{"company": "ACME", "title": "PM", "duration": "2022", "achievements": ["A"]}]

    async def rewrite_projects(collected, industry, position, skeleton_text=""):
        calls.append("projects")
        return [{"name": "P1", "role": "Owner", "tech_stack": ["Python"], "description": "D", "achievements": ["B"]}]

    async def derive(collected, industry, position, skeleton_text="", stream_callback=None):
        calls.append("derive")
        return {"summary": "fresh", "core_competencies": ["fresh"]}

    monkeypatch.setattr(flow, "build_skeleton", build_skeleton)
    monkeypatch.setattr(flow, "rewrite_experience", rewrite_experience)
    monkeypatch.setattr(flow, "rewrite_projects", rewrite_projects)
    monkeypatch.setattr(flow, "derive_summary_and_competencies", derive)

    state = {
        "skeleton": {"status": "done", "result": {"text": "cached skeleton", "source": "rag", "n_chunks": 3}},
        "derive": {"status": "done", "result": {"summary": "cached", "core_competencies": ["cached"]}},
    }
    snapshots = []

    payload = await flow.generate_resume_payload_resumable(
        collected={
            "header": {"name": "Leon", "contact": {}},
            "education": [],
            "experience": [{"company": "ACME", "title": "PM", "duration": "2022", "achievements": ["A"]}],
            "projects": [{"name": "P1", "role": "Owner", "tech_stack": ["Python"], "description": "D", "achievements": ["B"]}],
            "skills": ["Python"],
        },
        industry="互联网/软件",
        position="AI产品经理",
        generation_state=state,
        state_callback=lambda s: snapshots.append(copy.deepcopy(s)),
    )

    assert calls == ["experience", "projects"]
    assert payload["skeleton"]["text"] == "cached skeleton"
    assert payload["resume"]["summary"] == "cached"
    assert payload["resume"]["experience"][0]["company"] == "ACME"
    assert snapshots[-1]["rewrite_projects"]["status"] == "done"
