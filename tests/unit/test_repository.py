# -*- coding: utf-8 -*-
"""v2.1 M4.2: Repository round-trip 测试。

覆盖 SqliteBackend 的核心写读路径：
- resumes / jds / matches / optimizations / knowledge_chunks 的 insert ↔ get 一致性
- soft_delete_jd 级联到 knowledge_chunks
- update_match_applied / update_match_feedback / update_optimization_adopted
- insert_chunks_batch + get_chunks_by_jd embedding round-trip
"""
from __future__ import annotations


def _sample_resume():
    return {
        "user_id": "default",
        "name": "Leon",
        "phone": "12345678",
        "email": "leon@example.com",
        "summary": "AI PM with 5y exp",
        "skills": ["Python", "LLM", "SQL"],
        "experience_years": 5,
        "domains": ["AI"],
        "target_roles": ["AI PM"],
        "preferred_locations": ["HK"],
        "education": [{"school": "CUHK", "degree": "MSc"}],
        "projects": [{"name": "JobHunter", "desc": "RAG"}],
    }


def _sample_jd():
    return {
        "user_id": "default",
        "url": "https://example.com/jd/123",
        "title": "AI Product Manager",
        "company": "ACME",
        "location": "HK",
        "raw_text": "岗位职责：负责 AI 产品。任职要求：3 年以上 PM 经验。",
        "skills_required": ["LLM", "PRD"],
        "source": "manual",
        "platform": "jobsdb",
        "language": "zh",
    }


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------

class TestResumeRoundTrip:
    def test_insert_get(self, tmp_db):
        rid = tmp_db.insert_resume(_sample_resume())
        got = tmp_db.get_resume(rid)
        assert got is not None
        assert got["name"] == "Leon"
        assert got["skills"] == ["Python", "LLM", "SQL"]
        assert got["experience_years"] == 5
        assert got["education"] == [{"school": "CUHK", "degree": "MSc"}]

    def test_list_and_soft_delete(self, tmp_db):
        rid = tmp_db.insert_resume(_sample_resume())
        assert len(tmp_db.list_resumes()) == 1
        tmp_db.soft_delete_resume(rid)
        assert tmp_db.get_resume(rid) is None
        assert tmp_db.list_resumes() == []


# ---------------------------------------------------------------------------
# JD
# ---------------------------------------------------------------------------

class TestJDRoundTrip:
    def test_insert_get(self, tmp_db):
        jid = tmp_db.insert_jd(_sample_jd())
        got = tmp_db.get_jd(jid)
        assert got is not None
        assert got["title"] == "AI Product Manager"
        assert got["company"] == "ACME"
        assert got["skills_required"] == ["LLM", "PRD"]

    def test_get_by_url(self, tmp_db):
        jid = tmp_db.insert_jd(_sample_jd())
        got = tmp_db.get_jd_by_url("https://example.com/jd/123")
        assert got is not None and got["id"] == jid

    def test_list(self, tmp_db):
        tmp_db.insert_jd(_sample_jd())
        rows = tmp_db.list_jds()
        assert len(rows) == 1


# ---------------------------------------------------------------------------
# Match history
# ---------------------------------------------------------------------------

class TestMatchHistory:
    def test_insert_list(self, tmp_db):
        rid = tmp_db.insert_resume(_sample_resume())
        jid = tmp_db.insert_jd(_sample_jd())
        mid = tmp_db.insert_match({
            "resume_id": rid, "jd_id": jid, "score": 87,
            "reasoning": "good fit",
            "matched_skills": ["LLM"], "missing_skills": ["Java"],
            "gaps": ["Java"], "recommendations": [{"section": "skills", "text": "add"}],
        })
        rows = tmp_db.list_matches()
        assert len(rows) == 1
        assert rows[0]["id"] == mid
        assert rows[0]["score"] == 87
        assert rows[0]["matched_skills"] == ["LLM"]

    def test_update_applied(self, tmp_db):
        rid = tmp_db.insert_resume(_sample_resume())
        jid = tmp_db.insert_jd(_sample_jd())
        mid = tmp_db.insert_match({"resume_id": rid, "jd_id": jid, "score": 80})
        tmp_db.update_match_applied(mid, applied=1)
        rows = tmp_db.list_matches()
        assert rows[0]["applied"] == 1
        assert rows[0]["applied_at"]  # 自动填了时间

    def test_update_feedback(self, tmp_db):
        rid = tmp_db.insert_resume(_sample_resume())
        jid = tmp_db.insert_jd(_sample_jd())
        mid = tmp_db.insert_match({"resume_id": rid, "jd_id": jid, "score": 80})
        tmp_db.update_match_feedback(mid, "interview")
        rows = tmp_db.list_matches()
        assert rows[0]["user_feedback"] == "interview"


# ---------------------------------------------------------------------------
# Optimizations
# ---------------------------------------------------------------------------

class TestOptimizations:
    def test_insert_list_adopt(self, tmp_db):
        jid = tmp_db.insert_jd(_sample_jd())
        oid = tmp_db.insert_optimization({
            "jd_id": jid, "section": "skills",
            "original_content": "Python", "suggested_content": "Python, LLM",
            "reason": "JD 要求 LLM",
        })
        rows = tmp_db.list_optimizations(jd_id=jid)
        assert len(rows) == 1 and rows[0]["id"] == oid
        assert rows[0]["user_adopted"] == 0
        tmp_db.update_optimization_adopted(oid, 1)
        rows2 = tmp_db.list_optimizations(jd_id=jid)
        assert rows2[0]["user_adopted"] == 1


# ---------------------------------------------------------------------------
# Knowledge chunks + soft-delete cascade
# ---------------------------------------------------------------------------

class TestChunks:
    def test_insert_batch_round_trip(self, tmp_db):
        jid = tmp_db.insert_jd(_sample_jd())
        chunks = [
            {"chunk_text": "负责 AI 产品规划", "chunk_type": "responsibility",
             "heading_path": ["岗位职责"], "embedding": [0.1, 0.2, 0.3, 0.4]},
            {"chunk_text": "3 年 PM 经验", "chunk_type": "requirement",
             "heading_path": ["任职要求"], "embedding": [0.5, 0.6, 0.7, 0.8]},
        ]
        ids = tmp_db.insert_chunks_batch(jid, chunks)
        assert len(ids) == 2

        rows = tmp_db.get_chunks_by_jd(jid)
        assert len(rows) == 2
        # embedding 反序列化正确
        types = {r["chunk_type"] for r in rows}
        assert types == {"responsibility", "requirement"}
        emb0 = [r for r in rows if r["chunk_type"] == "responsibility"][0]["embedding"]
        assert emb0 == [0.1, 0.2, 0.3, 0.4]

    def test_soft_delete_jd_cascades(self, tmp_db):
        jid = tmp_db.insert_jd(_sample_jd())
        tmp_db.insert_chunks_batch(jid, [
            {"chunk_text": "x", "chunk_type": "overview", "embedding": [0.1] * 4}
        ])
        assert len(tmp_db.get_chunks_by_jd(jid)) == 1
        tmp_db.soft_delete_jd(jid)
        # 级联：chunks 也被软删
        assert tmp_db.get_chunks_by_jd(jid) == []
        assert tmp_db.get_jd(jid) is None


# ---------------------------------------------------------------------------
# Quality checks
# ---------------------------------------------------------------------------

class TestQualityChecks:
    def test_insert_list(self, tmp_db):
        cid = tmp_db.insert_quality_check({
            "check_type": "llm_latency", "target_table": "match_history",
            "target_id": "abc", "score": 100,
            "details": {"latency_ms": 1234, "tokens": 500},
        })
        assert isinstance(cid, int)
        rows = tmp_db.list_quality_checks(check_type="llm_latency")
        assert len(rows) == 1
        assert rows[0]["details"] == {"latency_ms": 1234, "tokens": 500}
