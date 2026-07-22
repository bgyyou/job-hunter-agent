# -*- coding: utf-8 -*-
"""v4 T1.2：多用户数据隔离测试 — 用户 A 的数据，用户 B 不可见、不可操作。

覆盖三条主数据路径：
- 简历库（resumes / 版本线 / 主简历 / 克隆）
- JD 库（用户私有 JD；公共 JD 两边都可见）
- Flow A 草稿（flow_a_drafts）
"""
from __future__ import annotations

import pytest

from services.flow_a_draft_service import FlowADraftService
from services.jd_library_service import (
    JdLibraryError,
    delete_user_jd,
    get_visible_jd,
    insert_user_jd,
    list_visible_jds,
)
from services.resume_library_service import (
    ResumeLibraryError,
    clone_resume,
    get_primary_resume,
    list_resume_versions,
    set_primary_resume,
)

USER_A = "user-aaa"
USER_B = "user-bbb"


def _resume(user_id: str, name: str = "张三"):
    return {
        "user_id": user_id,
        "name": name,
        "phone": "13800000000",
        "email": "z@example.com",
        "summary": "AI 产品经理",
        "skills": ["Python"],
        "experience_years": 5,
        "domains": ["AI"],
        "target_roles": ["AI产品经理"],
        "preferred_locations": ["深圳"],
    }


def _jd_payload(user_id: str, title: str = "AI 产品经理"):
    return {
        "user_id": user_id,
        "title": title,
        "company": "某公司",
        "raw_text": "岗位职责：负责 AI 产品规划",
        "source": "manual",
    }


class TestResumeIsolation:
    def test_b_cannot_list_a_resumes(self, tmp_db):
        tmp_db.insert_resume(_resume(USER_A))
        assert list_resume_versions(tmp_db, USER_B) == []
        assert len(list_resume_versions(tmp_db, USER_A)) == 1

    def test_b_cannot_get_a_primary_resume(self, tmp_db):
        rid = tmp_db.insert_resume(_resume(USER_A))
        set_primary_resume(tmp_db, USER_A, rid)
        assert get_primary_resume(tmp_db, USER_B) is None
        assert get_primary_resume(tmp_db, USER_A) is not None

    def test_b_cannot_set_primary_on_a_resume(self, tmp_db):
        rid = tmp_db.insert_resume(_resume(USER_A))
        with pytest.raises(ResumeLibraryError):
            set_primary_resume(tmp_db, USER_B, rid)

    def test_b_cannot_clone_a_resume(self, tmp_db):
        rid = tmp_db.insert_resume(_resume(USER_A))
        with pytest.raises(ResumeLibraryError):
            clone_resume(tmp_db, rid, USER_B)


class TestJdIsolation:
    def test_b_cannot_see_a_private_jd(self, tmp_db):
        jd_id = insert_user_jd(tmp_db, USER_A, _jd_payload(USER_A))
        assert [j["id"] for j in list_visible_jds(tmp_db, USER_B)] == []
        assert [j["id"] for j in list_visible_jds(tmp_db, USER_A)] == [jd_id]

    def test_b_cannot_get_a_private_jd_by_id(self, tmp_db):
        jd_id = insert_user_jd(tmp_db, USER_A, _jd_payload(USER_A))
        assert get_visible_jd(tmp_db, USER_B, jd_id) is None
        assert get_visible_jd(tmp_db, USER_A, jd_id) is not None

    def test_b_cannot_delete_a_jd(self, tmp_db):
        jd_id = insert_user_jd(tmp_db, USER_A, _jd_payload(USER_A))
        with pytest.raises(JdLibraryError):
            delete_user_jd(tmp_db, USER_B, jd_id)
        assert get_visible_jd(tmp_db, USER_A, jd_id) is not None

    def test_public_jd_visible_to_both(self, tmp_db):
        jd_id = insert_user_jd(tmp_db, USER_A, _jd_payload(USER_A))
        conn = tmp_db._get_conn()
        try:
            conn.execute("UPDATE jds SET is_public = 1 WHERE id = ?", (jd_id,))
            conn.commit()
        finally:
            conn.close()
        assert get_visible_jd(tmp_db, USER_B, jd_id) is not None


class TestFlowADraftIsolation:
    def test_b_cannot_see_a_drafts(self, tmp_db):
        svc_a = FlowADraftService(tmp_db, USER_A)
        draft_id = svc_a.upsert_draft({"basic": {"name": "张三"}})

        svc_b = FlowADraftService(tmp_db, USER_B)
        assert svc_b.get_latest_recoverable_draft() is None
        assert svc_b.get_draft(draft_id) is None
        assert svc_a.get_draft(draft_id) is not None

    def test_b_cannot_abandon_a_draft(self, tmp_db):
        svc_a = FlowADraftService(tmp_db, USER_A)
        draft_id = svc_a.upsert_draft({"basic": {"name": "张三"}})

        FlowADraftService(tmp_db, USER_B).abandon_draft(draft_id)

        draft = svc_a.get_draft(draft_id)
        assert draft is not None
        assert draft.get("status") == "draft"
