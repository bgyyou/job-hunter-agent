# -*- coding: utf-8 -*-
"""v2.1 N3: JobHunterDB facade round-trip 测试。

JobHunterDB（database/repository.py）是 v2.0 的直连实现，
v2.1 主流程已切到 SqliteBackend，但 facade 仍被部分老代码与脚本引用，
保持核心 CRUD 路径有测试守住，避免后续重构破坏旧调用方。

不测的：
- insert_jd_from_parsed_pdf / search_similar_chunks 显式抛 NotImplementedError，
  v2.1 已改由 backend 实现，facade 此处仅留占位。
"""
from __future__ import annotations

import pytest

from database.repository import JobHunterDB


@pytest.fixture
def jhdb(tmp_path):
    db = JobHunterDB(db_path=str(tmp_path / "facade.db"))
    return db


def _resume():
    return {
        "name": "Leon", "phone": "12345", "email": "l@e.com",
        "summary": "PM", "skills": ["Py"], "experience_years": 4,
        "domains": ["AI"], "target_roles": ["PM"], "preferred_locations": ["HK"],
        "education": [{"school": "CUHK"}], "projects": [],
    }


def _jd(url="https://e.com/1"):
    return {
        "url": url, "title": "PM", "company": "ACME", "location": "HK",
        "raw_text": "岗位职责：A\n任职要求：B", "skills_required": ["LLM"],
        "source": "manual", "platform": "test",
    }


# ----- resume CRUD -----

def test_resume_insert_get_list(jhdb):
    rid = jhdb.insert_resume(_resume())
    got = jhdb.get_resume(rid)
    assert got["name"] == "Leon"
    assert got["skills"] == ["Py"]
    rows = jhdb.list_resumes()
    assert len(rows) == 1


def test_resume_soft_delete(jhdb):
    rid = jhdb.insert_resume(_resume())
    jhdb.soft_delete_resume(rid)
    assert jhdb.get_resume(rid) is None
    assert jhdb.list_resumes() == []


def test_resume_get_missing(jhdb):
    assert jhdb.get_resume("does-not-exist") is None


# ----- JD CRUD -----

def test_jd_insert_get_by_url(jhdb):
    jid = jhdb.insert_jd(_jd("https://e.com/x"))
    assert jhdb.get_jd(jid)["title"] == "PM"
    assert jhdb.get_jd_by_url("https://e.com/x")["id"] == jid


def test_jd_list_filter(jhdb):
    jhdb.insert_jd(_jd("https://e.com/a"))
    j2 = _jd("https://e.com/b"); j2["source"] = "crawler"
    jhdb.insert_jd(j2)
    assert len(jhdb.list_jds()) == 2
    assert len(jhdb.list_jds(source="crawler")) == 1


def test_jd_search(jhdb):
    jhdb.insert_jd(_jd("https://e.com/q1"))
    rows = jhdb.search_jds(keyword="ACME")
    assert len(rows) >= 1


def test_jd_soft_delete(jhdb):
    jid = jhdb.insert_jd(_jd())
    jhdb.soft_delete_jd(jid)
    assert jhdb.get_jd(jid) is None
    assert jhdb.list_jds() == []


def test_jd_get_missing(jhdb):
    assert jhdb.get_jd("missing") is None
    assert jhdb.get_jd_by_url("https://nowhere.example") is None


# ----- match -----

def test_match_insert_list(jhdb):
    rid = jhdb.insert_resume(_resume())
    jid = jhdb.insert_jd(_jd())
    mid = jhdb.insert_match({
        "resume_id": rid, "jd_id": jid, "score": 91,
        "reasoning": "fit", "matched_skills": ["a"], "missing_skills": ["b"],
        "gaps": [], "recommendations": [],
    })
    rows = jhdb.list_matches()
    assert rows[0]["id"] == mid
    assert rows[0]["score"] == 91


def test_match_list_filter(jhdb):
    rid = jhdb.insert_resume(_resume())
    j1 = jhdb.insert_jd(_jd("https://e.com/m1"))
    j2 = jhdb.insert_jd(_jd("https://e.com/m2"))
    jhdb.insert_match({"resume_id": rid, "jd_id": j1, "score": 80})
    jhdb.insert_match({"resume_id": rid, "jd_id": j2, "score": 70})
    assert len(jhdb.list_matches(jd_id=j1)) == 1
    assert len(jhdb.list_matches(resume_id=rid)) == 2


# ----- optimization -----

def test_optimization_full_flow(jhdb):
    jid = jhdb.insert_jd(_jd())
    oid = jhdb.insert_optimization({
        "jd_id": jid, "section": "skills",
        "original_content": "Py", "suggested_content": "Py, LLM",
        "reason": "JD",
    })
    rows = jhdb.list_optimizations(jd_id=jid)
    assert rows[0]["id"] == oid
    assert rows[0]["user_adopted"] == 0
    jhdb.update_optimization_adopted(oid, 1)
    assert jhdb.list_optimizations(jd_id=jid)[0]["user_adopted"] == 1


# ----- chunks -----

def test_chunk_insert_and_get(jhdb):
    jid = jhdb.insert_jd(_jd())
    cid = jhdb.insert_chunk({
        "jd_id": jid, "chunk_index": 0, "chunk_text": "x",
        "chunk_type": "overview", "embedding": [0.1, 0.2],
    })
    assert isinstance(cid, str) and len(cid) > 8


def test_chunks_batch_round_trip(jhdb):
    jid = jhdb.insert_jd(_jd())
    chunks = [
        {"chunk_text": "a", "chunk_type": "responsibility", "embedding": [0.1, 0.2]},
        {"chunk_text": "b", "chunk_type": "requirement", "embedding": [0.3, 0.4]},
    ]
    ids = jhdb.insert_chunks_batch(jid, chunks)
    assert len(ids) == 2
    rows = jhdb.get_chunks_by_jd(jid)
    assert len(rows) == 2
    assert {r["chunk_type"] for r in rows} == {"responsibility", "requirement"}


# ----- quality checks -----

def test_quality_check_insert_list(jhdb):
    qid = jhdb.insert_quality_check({
        "check_type": "llm_call", "target_table": "match_history",
        "target_id": "x", "score": 100,
        "details": {"latency_ms": 100, "tokens": 50},
    })
    assert isinstance(qid, int)
    rows = jhdb.list_quality_checks(check_type="llm_call")
    assert rows[0]["details"]["tokens"] == 50


def test_quality_check_filter_by_target(jhdb):
    jhdb.insert_quality_check({"check_type": "a", "target_table": "tA", "score": 1})
    jhdb.insert_quality_check({"check_type": "a", "target_table": "tB", "score": 2})
    rows = jhdb.list_quality_checks(target_table="tB")
    assert len(rows) == 1


# ----- stats -----

def test_get_stats_empty(jhdb):
    stats = jhdb.get_stats()
    for k in ["resumes", "jds", "match_history", "optimizations", "knowledge_chunks"]:
        assert stats[k] == 0


def test_get_stats_after_insert(jhdb):
    rid = jhdb.insert_resume(_resume())
    jid = jhdb.insert_jd(_jd())
    jhdb.insert_match({"resume_id": rid, "jd_id": jid, "score": 80})
    stats = jhdb.get_stats()
    assert stats["resumes"] == 1
    assert stats["jds"] == 1
    assert stats["match_history"] == 1


# ----- JSON helpers (private but worth covering) -----

def test_json_helpers_handle_none_and_garbage(jhdb):
    assert jhdb._json_serialize(None) is None
    assert jhdb._json_serialize("already-str") == "already-str"
    assert jhdb._json_deserialize(None) == []
    assert jhdb._json_deserialize("not json{") == []
    assert jhdb._json_deserialize('["ok"]') == ["ok"]


# ----- not-yet-implemented placeholders -----

def test_not_implemented_methods(jhdb):
    with pytest.raises(NotImplementedError):
        jhdb.insert_jd_from_parsed_pdf("/tmp/x.pdf")
    with pytest.raises(NotImplementedError):
        jhdb.search_similar_chunks("query")
