# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from services.jd_library_service import (
    JdLibraryError,
    cleanup_garbage_public_jds,
    count_visible_jds,
    delete_user_jd,
    ensure_public_seed_jds,
    get_visible_jd,
    insert_user_jd,
    is_garbage_jd,
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




def test_count_visible_jds_matches_filters(tmp_db):
    insert_user_jd(tmp_db, "user-1", _jd("https://manual.example/pm", source="manual", title="AI PM"))
    insert_user_jd(tmp_db, "user-1", _jd("https://manual.example/data", source="manual_batch", title="Data PM"))
    insert_user_jd(tmp_db, "user-2", _jd("https://manual.example/other", source="manual", title="Other PM"))

    assert count_visible_jds(tmp_db, "user-1") == 2
    assert count_visible_jds(tmp_db, "user-1", source="manual_batch") == 1
    assert count_visible_jds(tmp_db, "user-1", search="Data") == 1


def test_list_visible_jds_pagination_after_100(tmp_db):
    for i in range(105):
        insert_user_jd(tmp_db, "user-1", _jd(f"https://manual.example/{i}", title=f"PM {i:03d}"))

    first_page = list_visible_jds(tmp_db, "user-1", limit=100, offset=0)
    second_page = list_visible_jds(tmp_db, "user-1", limit=20, offset=100)

    assert len(first_page) == 100
    assert len(second_page) == 5
    assert count_visible_jds(tmp_db, "user-1") == 105


def test_garbage_jd_detection_is_conservative():
    garbage = _jd(
        "https://liepin.example/verify",
        source="liepin_batch",
        title="安全验证",
    )
    garbage["company"] = ""
    garbage["raw_text"] = "人机验证 请先登录后继续访问 verify captcha"
    garbage["position_tag"] = None

    user_manual = dict(garbage)
    user_manual["source"] = "manual"

    assert is_garbage_jd(garbage) is True
    assert is_garbage_jd(user_manual) is False


def test_cleanup_garbage_public_jds_soft_deletes_only_public_crawled(tmp_db):
    garbage_id = tmp_db.insert_jd(_jd("https://liepin.example/verify", source="liepin_batch", title="安全验证"))
    good_id = tmp_db.insert_jd(_jd("https://liepin.example/good", source="liepin_batch", title="AI 产品经理"))
    manual_id = insert_user_jd(tmp_db, "user-1", _jd("https://manual.example/verify", source="manual", title="安全验证"))
    ensure_public_seed_jds(tmp_db)

    conn = tmp_db._get_conn()
    try:
        conn.execute("UPDATE jds SET company = '', raw_text = ?, position_tag = NULL WHERE id = ?", ("验证码 人机验证 请先登录 verify captcha", garbage_id))
        conn.execute("UPDATE jds SET company = '', raw_text = ?, position_tag = NULL WHERE id = ?", ("验证码 人机验证 请先登录 verify captcha", manual_id))
        conn.commit()
    finally:
        conn.close()

    preview = cleanup_garbage_public_jds(tmp_db, dry_run=True)
    assert {row["id"] for row in preview} == {garbage_id}

    removed = cleanup_garbage_public_jds(tmp_db, dry_run=False)
    assert {row["id"] for row in removed} == {garbage_id}
    assert get_visible_jd(tmp_db, "user-1", garbage_id) is None
    assert get_visible_jd(tmp_db, "user-1", good_id) is not None
    assert get_visible_jd(tmp_db, "user-1", manual_id) is not None


def test_search_and_source_filter(tmp_db):
    insert_user_jd(tmp_db, "user-1", _jd("https://manual.example/rag", source="manual", title="RAG 产品经理"))
    insert_user_jd(tmp_db, "user-1", _jd("https://manual.example/data", source="manual_batch", title="数据产品经理"))

    assert [r["title"] for r in list_visible_jds(tmp_db, "user-1", search="RAG 产品")] == ["RAG 产品经理"]
    assert {r["source"] for r in list_visible_jds(tmp_db, "user-1", source="manual_batch")} == {"manual_batch"}
    assert set(list_sources(tmp_db, "user-1")) == {"manual", "manual_batch"}
