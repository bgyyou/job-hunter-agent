# -*- coding: utf-8 -*-
"""v4 T1.1：登录门 — current_user_id / logout / session 默认值。

conftest 已 stub streamlit，import web_app 不会启动真实服务。
"""
from __future__ import annotations

import importlib

import pytest


def _import_web_app():
    return importlib.import_module("web_app")


@pytest.fixture
def web_app_mod():
    return _import_web_app()


@pytest.fixture(autouse=True)
def _clean_session(web_app_mod):
    """每个用例前后清掉身份态，避免用例间串扰。"""
    import streamlit as st

    for key in ("user_id", "user_display_name"):
        st.session_state[key] = None
    yield
    for key in ("user_id", "user_display_name"):
        st.session_state[key] = None


class TestCurrentUserId:
    def test_anonymous_when_not_logged_in(self, web_app_mod):
        assert web_app_mod.current_user_id() == web_app_mod.ANONYMOUS_USER_ID

    def test_returns_user_id_when_logged_in(self, web_app_mod):
        import streamlit as st

        st.session_state.user_id = "u-123"
        assert web_app_mod.current_user_id() == "u-123"

    def test_empty_string_falls_back_to_anonymous(self, web_app_mod):
        import streamlit as st

        st.session_state.user_id = ""
        assert web_app_mod.current_user_id() == web_app_mod.ANONYMOUS_USER_ID


class TestLogout:
    def test_logout_clears_identity_and_goes_landing(self, web_app_mod):
        import streamlit as st

        st.session_state.user_id = "u-123"
        st.session_state.user_display_name = "Leon"
        st.session_state.app_route = "flow_a"

        web_app_mod.logout_user()

        assert st.session_state.user_id is None
        assert st.session_state.user_display_name is None
        assert st.session_state.app_route == "landing"


class TestSessionDefaults:
    def test_init_session_state_has_auth_keys(self, web_app_mod):
        import streamlit as st

        web_app_mod.init_session_state()
        assert "user_id" in st.session_state
        assert "user_display_name" in st.session_state

    def test_db_uses_factory(self, web_app_mod):
        """init_app_services 不再硬编码 SqliteBackend，走 database.factory.get_db。"""
        import inspect

        src = inspect.getsource(web_app_mod.init_app_services)
        assert "get_db()" in src
        assert "SqliteBackend(" not in src


class TestQuotaWiring:
    """v4 T1.4：LLM 漏斗（run_async）前的配额检查接线。"""

    def test_quota_exceeded_warns_and_stops(self, web_app_mod, monkeypatch):
        import streamlit as st

        st.session_state.db = object()  # 只要有 db 就会走到 check_quota
        calls = {"warning": None, "stopped": False}
        monkeypatch.setattr(st, "warning", lambda msg: calls.__setitem__("warning", msg))
        monkeypatch.setattr(st, "stop", lambda: calls.__setitem__("stopped", True))

        def _raise(_self, _user_id):
            raise web_app_mod.QuotaExceededError("今日额度已用完，明天再来", scope="user")

        monkeypatch.setattr(web_app_mod.QuotaService, "check_quota", _raise)
        web_app_mod._check_llm_quota_or_stop()

        assert calls["warning"] == "今日额度已用完，明天再来"
        assert calls["stopped"] is True

    def test_quota_service_failure_does_not_block(self, web_app_mod, monkeypatch):
        import streamlit as st

        st.session_state.db = object()

        def _boom(_self, _user_id):
            raise RuntimeError("db down")

        monkeypatch.setattr(web_app_mod.QuotaService, "check_quota", _boom)
        web_app_mod._check_llm_quota_or_stop()  # 不抛即通过

    def test_no_db_skips_check(self, web_app_mod):
        import streamlit as st

        st.session_state.db = None
        web_app_mod._check_llm_quota_or_stop()  # 不抛即通过
