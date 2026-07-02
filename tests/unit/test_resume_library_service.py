# -*- coding: utf-8 -*-
"""services/resume_library_service.py 单元测试。"""
from __future__ import annotations

import pytest

from services.resume_library_service import (
    ResumeLibraryError,
    clone_resume,
    get_primary_resume,
    list_resume_versions,
    set_primary_resume,
)


def _resume(name: str = "张三", summary: str = "AI 产品经理，5年经验", user_id: str = "u1"):
    return {
        "user_id": user_id,
        "name": name,
        "phone": "13800000000",
        "email": "z@example.com",
        "summary": summary,
        "skills": ["Python", "LLM", "RAG"],
        "experience_years": 5,
        "domains": ["AI", "SaaS"],
        "target_roles": ["AI产品经理"],
        "preferred_locations": ["深圳"],
    }


def test_list_versions_empty(tmp_db):
    trees = list_resume_versions(tmp_db, "no-such-user")
    assert trees == []


def test_list_versions_single_root(tmp_db):
    rid = tmp_db.insert_resume(_resume())
    trees = list_resume_versions(tmp_db, "u1")
    assert len(trees) == 1
    assert trees[0]["root_id"] == rid
    assert len(trees[0]["versions"]) == 1
    assert trees[0]["versions"][0]["version"] == 1


def test_clone_creates_chain(tmp_db):
    r1 = tmp_db.insert_resume(_resume(name="v1"))
    r2 = clone_resume(tmp_db, r1, "u1", version_label="改版针对 JD2")
    r3 = clone_resume(tmp_db, r2, "u1", version_label="再改")

    trees = list_resume_versions(tmp_db, "u1")
    assert len(trees) == 1, "同一版本线应该聚合到一组"
    versions = trees[0]["versions"]
    assert len(versions) == 3
    assert [v["version"] for v in versions] == [1, 2, 3]
    assert versions[2]["version_label"] == "再改"
    assert versions[1]["parent_resume_id"] == r1
    assert versions[2]["parent_resume_id"] == r2


def test_clone_independent_roots(tmp_db):
    """两个独立的简历（无 parent 关系）应各成一组。"""
    r1 = tmp_db.insert_resume(_resume(name="A"))
    r2 = tmp_db.insert_resume(_resume(name="B"))
    trees = list_resume_versions(tmp_db, "u1")
    assert len(trees) == 2
    root_ids = {t["root_id"] for t in trees}
    assert root_ids == {r1, r2}


def test_set_primary_switches(tmp_db):
    r1 = tmp_db.insert_resume(_resume(name="A"))
    r2 = tmp_db.insert_resume(_resume(name="B"))
    set_primary_resume(tmp_db, "u1", r1)
    assert get_primary_resume(tmp_db, "u1")["id"] == r1

    set_primary_resume(tmp_db, "u1", r2)
    primary = get_primary_resume(tmp_db, "u1")
    assert primary["id"] == r2
    # 旧主简历应取消标记
    r1_now = tmp_db.get_resume(r1)
    assert r1_now["is_primary"] == 0


def test_set_primary_rejects_other_user(tmp_db):
    r = tmp_db.insert_resume(_resume(user_id="u1"))
    # u2 不能把 u1 的简历设为主
    with pytest.raises(ResumeLibraryError):
        set_primary_resume(tmp_db, "u2", r)


def test_clone_rejects_other_user(tmp_db):
    r = tmp_db.insert_resume(_resume(user_id="u1"))
    with pytest.raises(ResumeLibraryError):
        clone_resume(tmp_db, r, "u2")


def test_get_primary_fallback_to_latest(tmp_db):
    """没有任何 is_primary 时，fallback 到最新一份。"""
    tmp_db.insert_resume(_resume(name="old"))
    rid_new = tmp_db.insert_resume(_resume(name="new"))
    primary = get_primary_resume(tmp_db, "u1")
    assert primary is not None
    assert primary["id"] == rid_new


def test_clone_overrides_name(tmp_db):
    r1 = tmp_db.insert_resume(_resume(name="orig"))
    r2 = clone_resume(tmp_db, r1, "u1", overrides={"name": "v2改名"})
    fetched = tmp_db.get_resume(r2)
    assert fetched["name"] == "v2改名"
    # 父版本 name 不变
    assert tmp_db.get_resume(r1)["name"] == "orig"
