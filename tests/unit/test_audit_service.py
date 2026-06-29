# -*- coding: utf-8 -*-
"""Tests for services.audit_service.log_action helper.

埋点目标：用户关键操作（登录/简历/JD/match/优化）落到 audit_logs 表，
失败时静默吞掉异常，绝不影响业务主流程。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.audit_service import log_action


def test_log_action_writes_to_db(tmp_db):
    log_action(
        tmp_db,
        user_id="u1",
        action="resume.create",
        target_table="resumes",
        target_id="r1",
        details={"flow": "a"},
    )
    rows = tmp_db.list_audit_logs()
    assert len(rows) == 1
    row = rows[0]
    assert row["user_id"] == "u1"
    assert row["action"] == "resume.create"
    assert row["target_table"] == "resumes"
    assert row["target_id"] == "r1"
    assert row["status"] == "success"
    assert row["details"]["flow"] == "a"


def test_log_action_failure_status(tmp_db):
    log_action(
        tmp_db,
        user_id="u1",
        action="user.login.failure",
        status="failure",
        error_message="bad_password",
        details={"identifier": "test@example.com"},
    )
    row = tmp_db.list_audit_logs()[0]
    assert row["status"] == "failure"
    assert row["error_message"] == "bad_password"


def test_log_action_swallows_db_errors():
    """埋点失败绝不影响业务：模拟 db.insert_audit_log 抛异常，确认不向上传播。"""
    bad_db = MagicMock()
    bad_db.insert_audit_log.side_effect = RuntimeError("db unavailable")

    # 不应该 raise
    log_action(
        bad_db,
        user_id="u1",
        action="resume.create",
        target_table="resumes",
        target_id="r1",
    )
    bad_db.insert_audit_log.assert_called_once()


def test_log_action_minimal_args(tmp_db):
    """只传 user_id 和 action 也能落库。"""
    log_action(tmp_db, user_id="u1", action="user.logout")
    row = tmp_db.list_audit_logs()[0]
    assert row["action"] == "user.logout"
    assert row["target_table"] is None
    assert row["target_id"] is None
    assert row["status"] == "success"


def test_log_action_filter_by_user(tmp_db):
    log_action(tmp_db, user_id="u1", action="a1")
    log_action(tmp_db, user_id="u2", action="a2")
    assert len(tmp_db.list_audit_logs(user_id="u1")) == 1
    assert len(tmp_db.list_audit_logs(user_id="u2")) == 1
    assert len(tmp_db.list_audit_logs()) == 2
