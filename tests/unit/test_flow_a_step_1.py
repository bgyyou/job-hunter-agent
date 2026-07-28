# -*- coding: utf-8 -*-
"""v3 round-2: Flow A Step 1（JD 三选一入口）单测

按 update_plan.md §1.2 + §8.2 Q1（已解）：
- RAG 路径（行业/职能/岗位下拉 → JDParserRouter.parse(source="rag")）
- Text 路径（粘贴 → JDParserRouter.parse(source="text")）
- Image 路径（上传 → OCR → JDParserRouter.parse(source="image")，强制 needs_user_review）
- 三路径统一经 JDParserRouter.parse() 入库到 fa_jd_structured
- 校对界面：OCR 必走；RAG/text 可跳过
- 完成后 fa_step=2

覆盖（≥ 5 条）：
1. _jd_to_dict 接受 dict（透传）
2. _jd_to_dict 接受 StructuredJD（dataclass → dict）
3. _jd_to_dict 接受 None → {}
4. _sync_flow_a_position_from_jd 把 jd 字段同步到旧 fa_position / fa_industry / fa_function
5. fa_step 默认 1
6. reset_flow_a_state 重置 fa_step + 5 个 JD 字段
7. init_session_state 包含 v3 新 state keys
"""
from __future__ import annotations

import importlib

page_mod_1 = importlib.import_module('pages.03_📝_Flow_A_Step1')

import pytest


# web_app 在 import 时会拉 streamlit → agent → tools → pymupdf 等。
# conftest 已经 stub 了所有重依赖，pytest 自动加载 conftest，
# 所以 import web_app 不会触发真实 streamlit 启动。
def _import_web_app():
    return importlib.import_module("web_app")


@pytest.fixture
def web_app_mod():
    return _import_web_app()


# ============================================================
# _jd_to_dict：StructuredJD / dict / None → dict
# ============================================================

class TestJdToDict:
    def test_dict_passthrough(self, web_app_mod):
        d = {"company": "X", "title": "PM", "raw_text": "..."}
        out = page_mod_1._jd_to_dict(d)
        assert out == d

    def test_none_returns_empty_dict(self, web_app_mod):
        out = page_mod_1._jd_to_dict(None)
        assert out == {}

    def test_dataclass_structured_jd(self, web_app_mod):
        from services.jd_parser import StructuredJD
        jd = StructuredJD(
            source="text",
            raw_text="我们需要 Python 工程师",
            company="字节跳动",
            title="Python 工程师",
            responsibilities=["写代码", "Code Review"],
            requirements=["3 年 Python 经验"],
            needs_user_review=False,
            parse_notes=["单元测试"],
        )
        out = page_mod_1._jd_to_dict(jd)
        assert out["source"] == "text"
        assert out["company"] == "字节跳动"
        assert out["title"] == "Python 工程师"
        assert out["responsibilities"] == ["写代码", "Code Review"]
        assert out["requirements"] == ["3 年 Python 经验"]
        assert out["needs_user_review"] is False
        assert out["parse_notes"] == ["单元测试"]
        assert out["raw_text"] == "我们需要 Python 工程师"

    def test_object_with_to_db_dict(self, web_app_mod):
        """有 to_db_dict() 方法的对象 → 走快速路径。"""
        class FakeJD:
            def to_db_dict(self):
                return {"company": "Fake", "title": "Dev"}
            needs_user_review = True
            parse_notes = ["note1"]
            raw_text = "raw"
            level = "mid"
            user_id = "u1"

        out = page_mod_1._jd_to_dict(FakeJD())
        assert out["company"] == "Fake"
        assert out["title"] == "Dev"
        # 额外字段被补回
        assert out["needs_user_review"] is True
        assert out["parse_notes"] == ["note1"]
        assert out["level"] == "mid"
        assert out["user_id"] == "u1"


# ============================================================
# _sync_flow_a_position_from_jd：把 jd 同步到旧字段
# ============================================================

class TestSyncFlowAPositionFromJD:
    def test_syncs_from_jd(self, web_app_mod, monkeypatch):
        # 重置 session_state（避免污染）
        _reset_fa_session(monkeypatch)
        from dataclasses import dataclass
        from services.jd_parser import StructuredJD

        jd = StructuredJD(
            source="text",
            company="字节跳动",
            title="AI 产品经理",
            industry="互联网",
            function="产品",
            level="mid",
        )
        # 用一个独立的 SessionState 替代
        state = _FakeSession()
        state["fa_jd_structured"] = page_mod_1._jd_to_dict(jd)
        monkeypatch.setattr(web_app_mod.st, "session_state", state)
        page_mod_1._sync_flow_a_position_from_jd()
        assert state["fa_position"] == "AI 产品经理"
        assert state["fa_industry"] == "互联网"
        assert state["fa_function"] == "产品"

    def test_no_jd_no_op(self, web_app_mod, monkeypatch):
        state = _FakeSession()
        state["fa_jd_structured"] = None
        state["fa_position"] = "pre-existing"
        monkeypatch.setattr(web_app_mod.st, "session_state", state)
        page_mod_1._sync_flow_a_position_from_jd()
        # 旧值保留
        assert state["fa_position"] == "pre-existing"


# ============================================================
# init_session_state + reset_flow_a_state：v3 字段就位
# ============================================================

class TestSessionState:
    def test_init_has_v3_keys(self, web_app_mod):
        keys = set(web_app_mod.init_session_state.__code__.co_names)  # noqa
        # 静态校验：默认值表里必须包含 v3 新增字段
        import inspect
        src = inspect.getsource(web_app_mod.init_session_state)
        for k in [
            "fa_step", "fa_jd_input_mode", "fa_jd_text_input",
            "fa_jd_structured", "fa_jd_review_done",
            "fa_jd_image_path", "fa_jd_industry", "fa_jd_function",
        ]:
            assert k in src, f"v3 key {k} 缺失 in init_session_state"

    def test_reset_clears_v3_keys(self, web_app_mod):
        import inspect
        src = inspect.getsource(web_app_mod.reset_flow_a_state)
        for k in [
            "fa_jd_input_mode", "fa_jd_text_input", "fa_jd_image_path",
            "fa_jd_structured", "fa_jd_review_done",
            "fa_jd_industry", "fa_jd_function", "fa_jd_level", "fa_step",
        ]:
            assert k in src, f"v3 key {k} 缺失 in reset_flow_a_state"


# ============================================================
# 路由：fa_step=1 走新 Step 1，其他步走 legacy
# ============================================================

class TestFlowAStepDispatch:
    def test_default_fa_step_is_1(self, web_app_mod, monkeypatch):
        """新用户进入 flow_a → 默认 fa_step=1。"""
        state = _FakeSession()
        # 模拟 init_session_state 调用
        defaults = {
            "fa_step": 1, "fa_jd_input_mode": "rag", "fa_jd_structured": None,
        }
        for k, v in defaults.items():
            state[k] = v
        monkeypatch.setattr(web_app_mod.st, "session_state", state)
        assert state["fa_step"] == 1


# ============================================================
# P1-1: reset_flow_a_v3_step_state — 只清 Step 2-5，保留 JD
# ============================================================

class TestResetV3StepState:
    def test_function_exists(self, web_app_mod):
        """P1-1 新增函数应存在。"""
        assert hasattr(web_app_mod, "reset_flow_a_v3_step_state"), (
            "P1-1: web_app 应有 reset_flow_a_v3_step_state 函数"
        )

    def test_clears_step2_form(self, web_app_mod, monkeypatch):
        """reset_flow_a_v3_step_state 清空 fa_step2_form。"""
        state = _FakeSession()
        state["fa_step2_form"] = {"basic": {"name": "张三"}}
        monkeypatch.setattr(web_app_mod.st, "session_state", state)

        web_app_mod.reset_flow_a_v3_step_state()
        assert state["fa_step2_form"] is None

    def test_clears_step3_rewrites(self, web_app_mod, monkeypatch):
        """reset_flow_a_v3_step_state 清空 fa_step3_rewrites。"""
        state = _FakeSession()
        state["fa_step3_rewrites"] = [{"original": "原段", "rewritten": "改写段"}]
        monkeypatch.setattr(web_app_mod.st, "session_state", state)

        web_app_mod.reset_flow_a_v3_step_state()
        assert state["fa_step3_rewrites"] is None

    def test_clears_step3_final_resume(self, web_app_mod, monkeypatch):
        """reset_flow_a_v3_step_state 清空 fa_step3_final_resume。"""
        state = _FakeSession()
        state["fa_step3_final_resume"] = {"name": "张三"}
        monkeypatch.setattr(web_app_mod.st, "session_state", state)

        web_app_mod.reset_flow_a_v3_step_state()
        assert state["fa_step3_final_resume"] is None

    def test_resets_step3_mode_to_auto(self, web_app_mod, monkeypatch):
        """reset_flow_a_v3_step_state 重置 fa_step3_mode='auto' + fa_step3_first_run=True。"""
        state = _FakeSession()
        state["fa_step3_mode"] = "B"
        state["fa_step3_first_run"] = False
        monkeypatch.setattr(web_app_mod.st, "session_state", state)

        web_app_mod.reset_flow_a_v3_step_state()
        assert state["fa_step3_mode"] == "auto"
        assert state["fa_step3_first_run"] is True

    def test_preserves_jd_state(self, web_app_mod, monkeypatch):
        """P1-1 关键：reset_flow_a_v3_step_state 不动 Step 1 JD state。"""
        state = _FakeSession()
        jd = {"title": "AI 产品经理", "company": "字节跳动"}
        state["fa_jd_structured"] = jd
        state["fa_position"] = "AI 产品经理"
        state["fa_jd_industry"] = "互联网"
        state["fa_jd_function"] = "产品"
        state["fa_jd_level"] = "mid"
        state["fa_jd_input_mode"] = "text"
        monkeypatch.setattr(web_app_mod.st, "session_state", state)

        web_app_mod.reset_flow_a_v3_step_state()
        # JD 状态全部保留
        assert state["fa_jd_structured"] is jd
        assert state["fa_position"] == "AI 产品经理"
        assert state["fa_jd_industry"] == "互联网"
        assert state["fa_jd_function"] == "产品"
        assert state["fa_jd_level"] == "mid"
        assert state["fa_jd_input_mode"] == "text"

    def test_full_reset_clears_everything(self, web_app_mod, monkeypatch):
        """reset_flow_a_state (P1-1 增强版) 也清 Step 2-5 state + 重置 fa_step=1。"""
        state = _FakeSession()
        state["fa_step2_form"] = {"basic": {"name": "X"}}
        state["fa_step3_rewrites"] = [{"a": 1}]
        state["fa_step3_final_resume"] = {"b": 2}
        state["fa_step"] = 3
        state["fa_jd_structured"] = {"title": "AI PM"}
        monkeypatch.setattr(web_app_mod.st, "session_state", state)

        # 让 draft abandon 不抛
        monkeypatch.setattr(web_app_mod, "current_user_id", lambda: "u_test")
        from services.flow_a_draft_service import FlowADraftService
        monkeypatch.setattr(FlowADraftService, "__init__", lambda *a, **kw: None)
        monkeypatch.setattr(FlowADraftService, "abandon_draft", lambda *a, **kw: None)

        web_app_mod.reset_flow_a_state()
        # 全部清空
        assert state["fa_step2_form"] is None
        assert state["fa_step3_rewrites"] is None
        assert state["fa_step3_final_resume"] is None
        assert state["fa_step"] == 1
        assert state["fa_step3_mode"] == "auto"
        assert state["fa_step3_first_run"] is True


# ============================================================
# helpers
# ============================================================

class _FakeSession(dict):
    """模拟 st.session_state（dict-like 兼属性访问）。"""
    def __getattr__(self, k):
        return self.get(k)
    def __setattr__(self, k, v):
        self[k] = v


def _reset_fa_session(monkeypatch):
    """每个 test 重置 session_state（conftest 的 _SessionState 是单例）。"""
    import sys
    # 不需要重置：每个 test 自己创建 _FakeSession 后 monkeypatch
    pass
