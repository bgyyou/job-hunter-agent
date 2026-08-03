# -*- coding: utf-8 -*-
"""P0-006：登录错误信息脱敏。

安全要求：login_user 对外抛出的 AuthError message 不区分「用户不存在 / 密码错误 /
账号锁定」三种场景，全部统一为一个中性文案。攻击者无法通过错误信息差异
枚举账号存在性。

Backend 侧仍可记录详细 error_message（audit_logs.error_message / loguru），
此处只断言 raise 的 .args[0]。
"""
from __future__ import annotations

import pytest

from services.auth_service import AuthError, AuthService


_OBFUSCATED_MSG = "邮箱/手机号或密码错误"


def _exc_msg(exc_info) -> str:
    """从 pytest.raises 上下文拿 raise message。"""
    return exc_info.value.args[0]


def test_unknown_user_returns_obfuscated_message(tmp_db):
    """场景 1：账号不存在 — 对外 message 统一。"""
    auth = AuthService(tmp_db)

    with pytest.raises(AuthError) as exc_info:
        auth.login_user(identifier="nobody@example.com", password="any_password")

    assert _exc_msg(exc_info) == _OBFUSCATED_MSG


def test_wrong_password_returns_obfuscated_message(tmp_db):
    """场景 2：密码错误（账号存在） — 对外 message 必须与"用户不存在"分支一致。"""
    auth = AuthService(tmp_db)
    auth.register_user(email="a@example.com", password="password123")

    with pytest.raises(AuthError) as exc_info:
        auth.login_user(identifier="a@example.com", password="wrong_password")

    assert _exc_msg(exc_info) == _OBFUSCATED_MSG


def test_locked_account_returns_obfuscated_message(tmp_db):
    """场景 3：账号锁定 — 对外 message 必须与上述两种一致（不允许用具体细节区分）。"""
    auth = AuthService(tmp_db)
    auth.register_user(email="a@example.com", password="password123")

    # 触发 5 次失败以达到 _LOCKOUT_MAX_FAILURES
    for _ in range(5):
        with pytest.raises(AuthError):
            auth.login_user(identifier="a@example.com", password="wrongpass")

    # 第 6 次即使密码正确也被锁定 — 对外 message 仍然统一
    with pytest.raises(AuthError) as exc_info:
        auth.login_user(identifier="a@example.com", password="password123")

    assert _exc_msg(exc_info) == _OBFUSCATED_MSG


def test_login_error_messages_do_not_leak_account_existence(tmp_db):
    """强保证：三种场景的 message 字符串完全一致。"""
    auth = AuthService(tmp_db)
    auth.register_user(email="a@example.com", password="password123")

    msgs = []

    # 1. 用户不存在
    with pytest.raises(AuthError) as exc_info:
        auth.login_user(identifier="ghost@example.com", password="x")
    msgs.append(_exc_msg(exc_info))

    # 2. 密码错误（账号存在）— 同样使用新脱敏文案
    with pytest.raises(AuthError) as exc_info:
        auth.login_user(identifier="a@example.com", password="plain_wrong")
    msgs.append(_exc_msg(exc_info))

    # 3. 账号锁定 — 累计失败直到锁
    _fail_until_locked(auth, "a@example.com", "plain_wrong2")
    with pytest.raises(AuthError) as exc_info:
        auth.login_user(identifier="a@example.com", password="password123")
    msgs.append(_exc_msg(exc_info))

    # 三条 message 字符串完全相等 — 攻击者无法做存在性判定
    assert msgs[0] == msgs[1] == msgs[2], (
        f"三种场景 message 必须一致,实际 {msgs!r}"
    )
    # 文案不应泄露场景化用语。注意:「密码错误」是 substring 「邮箱/手机号或密码错误」,
    # 改用更精确的"账号不存在"/"密码不正确"等历史区分文案做反向检查。
    FORBIDDEN_PHRASES = ["锁定", "账号不存在", "用户不存在", "密码不正确", "账号或密码不正确"]
    assert all(
        not any(p in m for p in FORBIDDEN_PHRASES)
        for m in msgs
    ), f"文案仍泄露账号状态细节: {msgs!r}"


def _fail_until_locked(auth: AuthService, identifier: str, password: str) -> None:
    """累计失败直到下次调用会触发锁定。"""
    from services.auth_service import _LOCKOUT_MAX_FAILURES

    for _ in range(_LOCKOUT_MAX_FAILURES):
        with pytest.raises(AuthError):
            auth.login_user(identifier=identifier, password=password)


def test_backend_audit_log_still_records_specific_reason(tmp_db):
    """Backend 侧 audit log 的 error_message 字段仍保留具体错误码（bad_password / user_not_found / locked_out）。
    这些是 backend 记录，不暴露给前端，不影响对外文案脱敏。
    """
    auth = AuthService(tmp_db)

    # 1. unknown user → audit error_message='user_not_found'
    with pytest.raises(AuthError):
        auth.login_user(identifier="ghost@example.com", password="x")
    rows = tmp_db.list_audit_logs(action="user.login.failure")
    assert any(r["error_message"] == "user_not_found" for r in rows)

    # 2. wrong password → audit error_message='bad_password'
    auth.register_user(email="b@example.com", password="password123")
    with pytest.raises(AuthError):
        auth.login_user(identifier="b@example.com", password="wrong")
    rows = tmp_db.list_audit_logs(action="user.login.failure")
    assert any(r["error_message"] == "bad_password" for r in rows)
