# -*- coding: utf-8 -*-
"""SqliteBackend 端到端 round-trip 覆盖（P0-1 合并自原 test_repository_facade）。

原 test_repository_facade.py 测的是 v2.0 的 JobHunterDB facade，
v2.1 已统一到 SqliteBackend；本文件把 facade 用例迁移过来，
直接打 SqliteBackend，避免双套实现各自维护。
"""
from __future__ import annotations

import pytest


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

def test_resume_insert_get_list(tmp_db):
    rid = tmp_db.insert_resume(_resume())
    got = tmp_db.get_resume(rid)
    assert got["name"] == "Leon"
    assert got["skills"] == ["Py"]
    rows = tmp_db.list_resumes()
    assert len(rows) == 1


def test_resume_soft_delete(tmp_db):
    rid = tmp_db.insert_resume(_resume())
    tmp_db.soft_delete_resume(rid)
    assert tmp_db.get_resume(rid) is None
    assert tmp_db.list_resumes() == []


def test_resume_get_missing(tmp_db):
    assert tmp_db.get_resume("does-not-exist") is None


# ----- JD CRUD -----

def test_jd_insert_get_by_url(tmp_db):
    jid = tmp_db.insert_jd(_jd("https://e.com/x"))
    assert tmp_db.get_jd(jid)["title"] == "PM"
    assert tmp_db.get_jd_by_url("https://e.com/x")["id"] == jid


def test_jd_list_filter(tmp_db):
    tmp_db.insert_jd(_jd("https://e.com/a"))
    j2 = _jd("https://e.com/b"); j2["source"] = "crawler"
    tmp_db.insert_jd(j2)
    assert len(tmp_db.list_jds()) == 2
    assert len(tmp_db.list_jds(source="crawler")) == 1


def test_jd_search(tmp_db):
    tmp_db.insert_jd(_jd("https://e.com/q1"))
    rows = tmp_db.search_jds(keyword="ACME")
    assert len(rows) >= 1


def test_jd_soft_delete(tmp_db):
    jid = tmp_db.insert_jd(_jd())
    tmp_db.soft_delete_jd(jid)
    assert tmp_db.get_jd(jid) is None
    assert tmp_db.list_jds() == []


def test_jd_get_missing(tmp_db):
    assert tmp_db.get_jd("missing") is None
    assert tmp_db.get_jd_by_url("https://nowhere.example") is None


def test_jd_insert_duplicate_url_returns_real_id(tmp_db):
    """P0-2 回归：URL 重复时 insert_jd 必须返回数据库里的真实 id，
    而不是新生成的伪 UUID。这是 INSERT OR IGNORE 的静默跳过坑。"""
    url = "https://e.com/dup"
    first_id = tmp_db.insert_jd(_jd(url))
    second_id = tmp_db.insert_jd(_jd(url))
    assert first_id == second_id
    assert tmp_db.get_jd(first_id) is not None
    # 数据库里应该只有一条
    assert len(tmp_db.list_jds()) == 1


# ----- match -----

def test_match_insert_list(tmp_db):
    rid = tmp_db.insert_resume(_resume())
    jid = tmp_db.insert_jd(_jd())
    mid = tmp_db.insert_match({
        "resume_id": rid, "jd_id": jid, "score": 91,
        "reasoning": "fit", "matched_skills": ["a"], "missing_skills": ["b"],
        "gaps": [], "recommendations": [],
    })
    rows = tmp_db.list_matches()
    assert rows[0]["id"] == mid
    assert rows[0]["score"] == 91


def test_match_list_filter(tmp_db):
    rid = tmp_db.insert_resume(_resume())
    j1 = tmp_db.insert_jd(_jd("https://e.com/m1"))
    j2 = tmp_db.insert_jd(_jd("https://e.com/m2"))
    tmp_db.insert_match({"resume_id": rid, "jd_id": j1, "score": 80})
    tmp_db.insert_match({"resume_id": rid, "jd_id": j2, "score": 70})
    assert len(tmp_db.list_matches(jd_id=j1)) == 1
    assert len(tmp_db.list_matches(resume_id=rid)) == 2


# ----- optimization -----

def test_optimization_full_flow(tmp_db):
    jid = tmp_db.insert_jd(_jd())
    oid = tmp_db.insert_optimization({
        "jd_id": jid, "section": "skills",
        "original_content": "Py", "suggested_content": "Py, LLM",
        "reason": "JD",
    })
    rows = tmp_db.list_optimizations(jd_id=jid)
    assert rows[0]["id"] == oid
    assert rows[0]["user_adopted"] == 0
    tmp_db.update_optimization_adopted(oid, 1)
    assert tmp_db.list_optimizations(jd_id=jid)[0]["user_adopted"] == 1


# ----- chunks -----

def test_chunk_insert_and_get(tmp_db):
    jid = tmp_db.insert_jd(_jd())
    cid = tmp_db.insert_chunk({
        "jd_id": jid, "chunk_index": 0, "chunk_text": "x",
        "chunk_type": "overview", "embedding": [0.1, 0.2],
    })
    assert isinstance(cid, str) and len(cid) > 8


def test_chunks_batch_round_trip(tmp_db):
    jid = tmp_db.insert_jd(_jd())
    chunks = [
        {"chunk_text": "a", "chunk_type": "responsibility", "embedding": [0.1, 0.2]},
        {"chunk_text": "b", "chunk_type": "requirement", "embedding": [0.3, 0.4]},
    ]
    ids = tmp_db.insert_chunks_batch(jid, chunks)
    assert len(ids) == 2
    rows = tmp_db.get_chunks_by_jd(jid)
    assert len(rows) == 2
    assert {r["chunk_type"] for r in rows} == {"responsibility", "requirement"}


# ----- quality checks -----

def test_quality_check_insert_list(tmp_db):
    qid = tmp_db.insert_quality_check({
        "check_type": "llm_call", "target_table": "match_history",
        "target_id": "x", "score": 100,
        "details": {"latency_ms": 100, "tokens": 50},
    })
    assert isinstance(qid, int)
    rows = tmp_db.list_quality_checks(check_type="llm_call")
    assert rows[0]["details"]["tokens"] == 50


def test_quality_check_filter_by_target(tmp_db):
    tmp_db.insert_quality_check({"check_type": "a", "target_table": "tA", "score": 1})
    tmp_db.insert_quality_check({"check_type": "a", "target_table": "tB", "score": 2})
    rows = tmp_db.list_quality_checks(target_table="tB")
    assert len(rows) == 1


# ----- stats -----

def test_get_stats_empty(tmp_db):
    stats = tmp_db.get_stats()
    for k in ["resumes", "jds", "match_history", "optimizations", "knowledge_chunks"]:
        assert stats[k] == 0


def test_get_stats_after_insert(tmp_db):
    rid = tmp_db.insert_resume(_resume())
    jid = tmp_db.insert_jd(_jd())
    tmp_db.insert_match({"resume_id": rid, "jd_id": jid, "score": 80})
    stats = tmp_db.get_stats()
    assert stats["resumes"] == 1
    assert stats["jds"] == 1
    assert stats["match_history"] == 1


# ----- JSON helpers (private but worth covering) -----

def test_json_helpers_handle_none_and_garbage(tmp_db):
    assert tmp_db._json_serialize(None) is None
    assert tmp_db._json_serialize("already-str") == "already-str"
    assert tmp_db._json_deserialize(None) == []
    assert tmp_db._json_deserialize("not json{") == []
    assert tmp_db._json_deserialize('["ok"]') == ["ok"]
