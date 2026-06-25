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
