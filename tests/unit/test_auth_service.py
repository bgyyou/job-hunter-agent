# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from services.auth_service import AuthError, AuthService


def test_register_email_user_normalizes_and_hides_password(tmp_db):
    auth = AuthService(tmp_db)
    user = auth.register_user(email="LEON@Example.COM", password="password123", name="Leon")

    assert user["email"] == "leon@example.com"
    assert user["name"] == "Leon"
    assert "password_hash" not in user
    assert auth.login_user(identifier="leon@example.com", password="password123")["id"] == user["id"]

    conn = tmp_db._get_conn()
    try:
        row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
        assert row["password_hash"] != "password123"
    finally:
        conn.close()


def test_register_phone_user_and_login(tmp_db):
    auth = AuthService(tmp_db)
    user = auth.register_user(phone="+86 138-0013-8000", password="password123")

    assert user["phone"] == "+8613800138000"
    assert auth.login_user(identifier="+8613800138000", password="password123")["id"] == user["id"]


def test_register_rejects_duplicate_email_and_phone(tmp_db):
    auth = AuthService(tmp_db)
    auth.register_user(email="a@example.com", phone="13800138000", password="password123")

    with pytest.raises(AuthError):
        auth.register_user(email="A@example.com", password="password123")
    with pytest.raises(AuthError):
        auth.register_user(phone="13800138000", password="password123")


def test_login_rejects_wrong_password(tmp_db):
    auth = AuthService(tmp_db)
    auth.register_user(email="a@example.com", password="password123")

    with pytest.raises(AuthError):
        auth.login_user(identifier="a@example.com", password="wrongpass")


def test_register_requires_valid_identifier_and_password(tmp_db):
    auth = AuthService(tmp_db)

    with pytest.raises(AuthError):
        auth.register_user(password="password123")
    with pytest.raises(AuthError):
        auth.register_user(email="not-email", password="password123")
    with pytest.raises(AuthError):
        auth.register_user(phone="abc", password="password123")
    with pytest.raises(AuthError):
        auth.register_user(email="a@example.com", password="short")


# ----- P1-16: 审计日志埋点 -----

def test_register_writes_audit_log(tmp_db):
    auth = AuthService(tmp_db)
    user = auth.register_user(email="a@example.com", password="password123", name="Leon")
    rows = tmp_db.list_audit_logs(action="user.register")
    assert len(rows) == 1
    assert rows[0]["user_id"] == user["id"]
    assert rows[0]["target_table"] == "users"
    assert rows[0]["target_id"] == user["id"]
    assert rows[0]["details"]["email"] == "a@example.com"


def test_login_success_writes_audit_log(tmp_db):
    auth = AuthService(tmp_db)
    auth.register_user(email="a@example.com", password="password123")
    # 清掉注册时的 audit log，只看 login
    tmp_db.list_audit_logs()
    auth.login_user(identifier="a@example.com", password="password123")
    success_rows = tmp_db.list_audit_logs(action="user.login.success")
    assert len(success_rows) == 1
    assert success_rows[0]["status"] == "success"


def test_login_failure_writes_audit_log(tmp_db):
    auth = AuthService(tmp_db)
    auth.register_user(email="a@example.com", password="password123")
    with pytest.raises(AuthError):
        auth.login_user(identifier="a@example.com", password="wrong")
    failure_rows = tmp_db.list_audit_logs(action="user.login.failure")
    assert len(failure_rows) == 1
    assert failure_rows[0]["status"] == "failure"
    assert failure_rows[0]["error_message"] == "bad_password"


def test_login_unknown_user_writes_audit_log(tmp_db):
    auth = AuthService(tmp_db)
    with pytest.raises(AuthError):
        auth.login_user(identifier="nobody@example.com", password="x")
    failure_rows = tmp_db.list_audit_logs(action="user.login.failure")
    assert len(failure_rows) == 1
    assert failure_rows[0]["error_message"] == "user_not_found"

