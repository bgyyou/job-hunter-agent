# -*- coding: utf-8 -*-
from __future__ import annotations

from services.auth_service import AuthService
from services.jd_library_service import ensure_public_seed_jds, insert_user_jd, list_visible_jds


def _jd(url: str, *, user_id: str = "default", source: str = "manual", title: str = "AI Product Manager"):
    return {
        "user_id": user_id,
        "url": url,
        "title": title,
        "company": "SeedCorp",
        "raw_text": "负责 AI 产品规划，要求熟悉 LLM、RAG 和 Agent。",
        "source": source,
        "parsed_sections": {"requirements": ["LLM", "RAG"]},
        "tags": ["LLM", "RAG"],
        "position_tag": "AI产品经理",
    }


def test_new_user_sees_public_crawled_jds_but_not_other_users_private_jds(tmp_db):
    public_id = tmp_db.insert_jd(_jd("https://jobsdb.example/seed", source="jobsdb_batch"))
    other_private_id = insert_user_jd(tmp_db, "other-user", _jd("https://manual.example/other", user_id="other-user"))

    user = AuthService(tmp_db).register_user(email="new@example.com", password="password123")
    ensure_public_seed_jds(tmp_db)

    visible = list_visible_jds(tmp_db, user["id"])
    visible_ids = {row["id"] for row in visible}

    assert public_id in visible_ids
    assert other_private_id not in visible_ids


def test_user_uploaded_jd_is_visible_alongside_public_seed(tmp_db):
    tmp_db.insert_jd(_jd("https://liepin.example/seed", source="liepin_batch"))
    user = AuthService(tmp_db).register_user(phone="13800138000", password="password123")
    own_id = insert_user_jd(tmp_db, user["id"], _jd("https://manual.example/own", title="Growth PM"))
    ensure_public_seed_jds(tmp_db)

    visible = list_visible_jds(tmp_db, user["id"])
    titles_by_id = {row["id"]: row["title"] for row in visible}

    assert own_id in titles_by_id
    assert "Growth PM" in titles_by_id.values()
    assert "AI Product Manager" in titles_by_id.values()
