# -*- coding: utf-8 -*-
"""本地账号 Auth service。

生产登录（微信/短信/邮件验证码）后续通过 provider/provider_subject 接入；
当前先用邮箱/手机号 + 密码跑通用户身份和数据归属。
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from services.audit_service import log_action


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^\+?\d{6,20}$")
_PBKDF2_ITERATIONS = 200_000


class AuthError(ValueError):
    """Raised when auth input is invalid or credentials are rejected."""


class AuthService:
    def __init__(self, db: Any):
        self.db = db

    def register_user(
        self,
        *,
        password: str,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        name: str = "",
    ) -> Dict[str, Any]:
        email_norm = self._normalize_email(email)
        phone_norm = self._normalize_phone(phone)
        if not email_norm and not phone_norm:
            raise AuthError("请填写邮箱或手机号")
        if len(password or "") < 8:
            raise AuthError("密码至少需要 8 位")
        if email_norm and self.get_user_by_email(email_norm):
            raise AuthError("该邮箱已注册")
        if phone_norm and self.get_user_by_phone(phone_norm):
            raise AuthError("该手机号已注册")

        salt = secrets.token_hex(16)
        user_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        conn = self.db._get_conn()
        try:
            conn.execute(
                """INSERT INTO users
                   (id, email, phone, name, password_hash, password_salt,
                    provider, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'local', ?, ?)""",
                (
                    user_id,
                    email_norm,
                    phone_norm,
                    (name or "").strip()[:80],
                    self._hash_password(password, salt),
                    salt,
                    now,
                    now,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        user = self.get_user(user_id)
        log_action(
            self.db,
            user_id=user_id,
            action="user.register",
            target_table="users",
            target_id=user_id,
            details={"email": email_norm, "phone": phone_norm, "name": (name or "").strip()[:80]},
        )
        return user

    def login_user(
        self,
        *,
        identifier: str,
        password: str,
    ) -> Dict[str, Any]:
        ident = (identifier or "").strip()
        user = self.get_user_by_email(self._normalize_email(ident)) if "@" in ident else self.get_user_by_phone(self._normalize_phone(ident))
        if not user:
            log_action(
                self.db,
                user_id="default",
                action="user.login.failure",
                status="failure",
                error_message="user_not_found",
                details={"identifier": ident[:80]},
            )
            raise AuthError("账号或密码不正确")
        stored = self._get_user_secret(user["id"])
        if not stored or not self._verify_password(password, stored["password_salt"], stored["password_hash"]):
            log_action(
                self.db,
                user_id=user["id"],
                action="user.login.failure",
                target_table="users",
                target_id=user["id"],
                status="failure",
                error_message="bad_password",
                details={"identifier": ident[:80]},
            )
            raise AuthError("账号或密码不正确")
        log_action(
            self.db,
            user_id=user["id"],
            action="user.login.success",
            target_table="users",
            target_id=user["id"],
            details={"identifier": ident[:80]},
        )
        return user

    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        return self._get_user_by("id", user_id)

    def get_user_by_email(self, email: Optional[str]) -> Optional[Dict[str, Any]]:
        if not email:
            return None
        return self._get_user_by("email", email)

    def get_user_by_phone(self, phone: Optional[str]) -> Optional[Dict[str, Any]]:
        if not phone:
            return None
        return self._get_user_by("phone", phone)

    def _get_user_by(self, field: str, value: str) -> Optional[Dict[str, Any]]:
        if field not in {"id", "email", "phone"}:
            raise ValueError("invalid user lookup field")
        conn = self.db._get_conn()
        try:
            row = conn.execute(
                f"SELECT id, email, phone, name, provider, provider_subject, created_at, updated_at "
                f"FROM users WHERE {field} = ? AND deleted_at IS NULL",
                (value,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def _get_user_secret(self, user_id: str) -> Optional[Dict[str, str]]:
        conn = self.db._get_conn()
        try:
            row = conn.execute(
                "SELECT password_hash, password_salt FROM users WHERE id = ? AND deleted_at IS NULL",
                (user_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def _normalize_email(email: Optional[str]) -> Optional[str]:
        if email is None:
            return None
        value = email.strip().lower()
        if not value:
            return None
        if not _EMAIL_RE.match(value):
            raise AuthError("邮箱格式不正确")
        return value

    @staticmethod
    def _normalize_phone(phone: Optional[str]) -> Optional[str]:
        if phone is None:
            return None
        value = re.sub(r"[\s\-()]", "", phone.strip())
        if not value:
            return None
        if not _PHONE_RE.match(value):
            raise AuthError("手机号格式不正确")
        return value

    @staticmethod
    def _hash_password(password: str, salt: str) -> str:
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            _PBKDF2_ITERATIONS,
        )
        return digest.hex()

    @classmethod
    def _verify_password(cls, password: str, salt: str, expected_hash: str) -> bool:
        actual = cls._hash_password(password, salt)
        return hmac.compare_digest(actual, expected_hash)
