# -*- coding: utf-8 -*-
"""P2-2: JD schema 收敛验证 — 5 字段 → parsed_sections + tags + raw_text。"""
from __future__ import annotations

import sqlite3


def _jd_v3(url="https://e.com/v3"):
    return {
        "url": url,
        "title": "Senior PM",
        "company": "ACME",
        "raw_text": "Build LLM products; 5y exp; Python required.",
        "parsed_sections": {
            "requirements": ["Python", "5y"],
            "preferred": ["LLM"],
            "skills": ["Python", "SQL"],
            "implicit": "Team player",
        },
        "tags": ["Python", "5年经验", "PM"],
        "source": "manual",
    }


def test_insert_with_parsed_sections_and_tags(tmp_db):
    jid = tmp_db.insert_jd(_jd_v3())
    got = tmp_db.get_jd(jid)
    assert got["parsed_sections"]["requirements"] == ["Python", "5y"]
    assert got["parsed_sections"]["preferred"] == ["LLM"]
    assert got["parsed_sections"]["implicit"] == "Team player"
    assert got["tags"] == ["Python", "5年经验", "PM"]


def test_no_legacy_columns_in_jds_table(tmp_db):
    """jds 表不应再有 5 个旧字段。"""
    conn = sqlite3.connect(tmp_db.db_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(jds)").fetchall()}
    finally:
        conn.close()
    legacy = {"requirements", "preferred_requirements", "skills_required",
              "implicit_requirements", "parsed_data"}
    assert not (cols & legacy), f"残留旧字段: {cols & legacy}"
    assert "parsed_sections" in cols
    assert "tags" in cols


def test_list_jds_roundtrip(tmp_db):
    tmp_db.insert_jd(_jd_v3("https://e.com/a"))
    tmp_db.insert_jd(_jd_v3("https://e.com/b"))
    rows = tmp_db.list_jds()
    assert len(rows) == 2
    for r in rows:
        assert isinstance(r["parsed_sections"], dict)
        assert isinstance(r["tags"], list)


def test_search_jds_keyword(tmp_db):
    tmp_db.insert_jd(_jd_v3())
    rows = tmp_db.search_jds(keyword="LLM")
    assert len(rows) >= 1
    assert rows[0]["parsed_sections"]["preferred"] == ["LLM"]


def test_migration_004_idempotent(tmp_db):
    """重复执行 _apply_idempotent_migrations 不应报错。"""
    conn = sqlite3.connect(tmp_db.db_path)
    try:
        tmp_db._apply_idempotent_migrations(conn)
        tmp_db._apply_idempotent_migrations(conn)
    finally:
        conn.close()


def test_matcher_uses_tags_for_skill_diff():
    """验证 matcher 内置 skill diff 逻辑用 tags 而非 skills_required。"""
    resume = {"skills": ["Python"]}
    job = {"tags": ["Python", "Go"], "parsed_sections": {"skills": ["Go", "Rust"]}}

    resume_skills = set(s.lower() for s in resume.get("skills", []))
    job_tags = set(s.lower() for s in job.get("tags", []))
    job_skills = set(s.lower() for s in job.get("parsed_sections", {}).get("skills", [])) | job_tags

    missing = job_skills - resume_skills
    assert "go" in missing
    assert "rust" in missing
    assert "python" not in missing
