# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from services.jd_library_service import (
    JdLibraryError,
    delete_user_jd,
    ensure_public_seed_jds,
    get_visible_jd,
    insert_user_jd,
    list_sources,
    list_visible_jds,
)


def _jd(url: str, *, user_id: str = "default", source: str = "manual", title: str = "AI PM"):
    return {
        "user_id": user_id,
        "url": url,
        "title": title,
        "company": "ACME",
        "raw_text": f"{title} 岗位职责：负责 AI 产品规划。任职要求：LLM/RAG 经验。",
        "source": source,
        "position_tag": "AI产品经理",
        "parsed_sections": {"requirements": ["LLM"]},
        "tags": ["LLM", "RAG"],
    }


def test_public_seed_jds_visible_to_user(tmp_db):
    public_id = tmp_db.insert_jd(_jd("https://jobsdb.example/1", source="jobsdb_batch"))
    private_default_id = tmp_db.insert_jd(_jd("https://manual.example/1", source="manual"))

    changed = ensure_public_seed_jds(tmp_db)

    assert changed == 1
    rows = list_visible_jds(tmp_db, "user-1")
    ids = {r["id"] for r in rows}
    assert public_id in ids
    assert private_default_id not in ids


def test_insert_user_jd_is_private_to_user(tmp_db):
    jid = insert_user_jd(tmp_db, "user-1", _jd("https://manual.example/u1"))

    assert get_visible_jd(tmp_db, "user-1", jid)["user_id"] == "user-1"
    assert get_visible_jd(tmp_db, "user-2", jid) is None


def test_user_cannot_delete_public_jd(tmp_db):
    jid = tmp_db.insert_jd(_jd("https://liepin.example/1", source="liepin_batch"))
    ensure_public_seed_jds(tmp_db)

    with pytest.raises(JdLibraryError):
        delete_user_jd(tmp_db, "user-1", jid)
    assert get_visible_jd(tmp_db, "user-1", jid) is not None


def test_user_can_delete_own_jd(tmp_db):
    jid = insert_user_jd(tmp_db, "user-1", _jd("https://manual.example/u2"))

    delete_user_jd(tmp_db, "user-1", jid)

    assert get_visible_jd(tmp_db, "user-1", jid) is None


def test_search_and_source_filter(tmp_db):
    insert_user_jd(tmp_db, "user-1", _jd("https://manual.example/rag", source="manual", title="RAG 产品经理"))
    insert_user_jd(tmp_db, "user-1", _jd("https://manual.example/data", source="manual_batch", title="数据产品经理"))

    assert [r["title"] for r in list_visible_jds(tmp_db, "user-1", search="RAG 产品")] == ["RAG 产品经理"]
    assert {r["source"] for r in list_visible_jds(tmp_db, "user-1", source="manual_batch")} == {"manual_batch"}
    assert set(list_sources(tmp_db, "user-1")) == {"manual", "manual_batch"}
