# -*- coding: utf-8 -*-
"""v3 round-2: Flow A Step 3（模式 A/B/auto 改写）单测

按 update_plan.md §1.2 + §1.3 + §2.4：
- _score_resume 调 round-1 InformationScorer（不传 LLM 仍能跑）
- _compose_final_resume 把改写结果合并进简历 dict
- 模式 B 输出标记 _rewrite_mode="B" + rewrites 数组
- 模式 A 输出标记 _rewrite_mode="A"

覆盖（≥ 5 条）：
1. _score_resume 不抛异常（LLM 客户端未配置时降级到默认 B）
2. _compose_final_resume 保留原 resume 字段 + 注入 _rewrites / _rewrite_mode
3. _compose_final_resume 接受 RewriteResult（dataclass）
4. _compose_final_resume 接受 dict（{rewrites: [...], mode: "A"}）
5. _compose_final_resume 模式 B 标记 _rewrite_mode="B"
6. _render_rewrite_results 模式 A 不报异常
7. _render_rewrite_results 模式 B 不报异常
"""
from __future__ import annotations

import importlib

import pytest


def _import_web_app():
    return importlib.import_module("web_app")


@pytest.fixture
def web_app_mod():
    return _import_web_app()


# ============================================================
# _score_resume：InformationScorer 包装
# ============================================================

class TestScoreResume:
    def test_returns_dict_with_required_keys(self, web_app_mod):
        s = web_app_mod._score_resume({})
        assert isinstance(s, dict)
        assert "total_score" in s
        assert "recommended_mode" in s
        assert "reason" in s

    def test_empty_resume_low_score(self, web_app_mod):
        s = web_app_mod._score_resume({
            "name": "X", "phone": "1", "email": "x@x.com",
            "experience": [], "projects": [], "education": [],
        })
        # 空简历 → 信息量低 → 推荐 B
        assert s["recommended_mode"] in ("B", "A+B")

    def test_full_resume_high_score(self, web_app_mod):
        s = web_app_mod._score_resume({
            "name": "张三", "phone": "13800138000", "email": "z@z.com",
            "experience": [
                {"company": "字节", "title": "PM",
                 "description": "做产品 " * 50,
                 "achievements": ["促成 200 单成交", "GMV 120 万"]},
            ],
            "projects": [
                {"name": "AI", "description": "D " * 30,
                 "achievements": ["DAU 1000"]},
            ],
            "education": [{"school": "北大", "degree": "本科", "major": "CS"}],
            "skills": ["Python", "LLM"],
        })
        # 充分简历 → 推荐 A
        assert s["recommended_mode"] in ("A", "A+B")

    def test_no_llm_no_crash(self, web_app_mod, monkeypatch):
        """无 LLM 客户端时仍能跑（不抛异常）。"""
        # 模拟 LLM 客户端 None
        state = _FakeSession()
        state["llm_client"] = None
        monkeypatch.setattr(web_app_mod.st, "session_state", state)
        s = web_app_mod._score_resume({})
        assert s is not None


# ============================================================
# _compose_final_resume：改写结果合并
# ============================================================

class TestComposeFinalResume:
    def test_preserves_original_fields(self, web_app_mod):
        resume = {"name": "张三", "phone": "1", "experience": [{"company": "X"}]}
        from services.resume_rewriter import RewriteResult
        rw = RewriteResult(mode="A", rewrites=[
            {"section": "experience_0", "original": "x", "rewritten": "y"}
        ])
        out = web_app_mod._compose_final_resume(resume, rw, {})
        assert out["name"] == "张三"
        assert out["phone"] == "1"
        assert out["experience"] == [{"company": "X"}]

    def test_injects_rewrites(self, web_app_mod):
        resume = {"name": "X", "experience": []}
        from services.resume_rewriter import RewriteResult
        rw = RewriteResult(mode="A", rewrites=[
            {"section": "experience_0", "rewritten": "改写 1"},
            {"section": "experience_1", "rewritten": "改写 2"},
        ])
        out = web_app_mod._compose_final_resume(resume, rw, {})
        assert out["_rewrites"] == rw.rewrites
        assert out["_rewrite_mode"] == "A"
        assert len(out["_rewrites"]) == 2

    def test_accepts_dict_with_rewrites(self, web_app_mod):
        """兼容 dict 输入（to_dict() 后的产物）。"""
        resume = {"name": "X"}
        rw_dict = {
            "mode": "A",
            "rewrites": [{"section": "education_0", "rewritten": "改写"}],
            "warnings": [], "needs_user_review": True,
        }
        out = web_app_mod._compose_final_resume(resume, rw_dict, {})
        assert out["_rewrite_mode"] == "A"
        assert out["_rewrites"][0]["section"] == "education_0"

    def test_mode_b_marked(self, web_app_mod):
        """模式 B 输出 → _rewrite_mode="B"。"""
        resume = {"name": "X", "experience": []}
        from services.resume_rewriter import RewriteResult
        rw = RewriteResult(mode="B", rewrites=[
            {"section": "experience_0", "content": "模板段",
             "is_ai_generated": True, "anchored_keywords": ["销售转化"]}
        ])
        out = web_app_mod._compose_final_resume(resume, rw, {})
        assert out["_rewrite_mode"] == "B"
        assert out["_rewrites"][0]["is_ai_generated"] is True


# ============================================================
# _render_rewrite_results：UI 渲染（用 stub 不真渲染）
# ============================================================

class TestRenderRewriteResults:
    def test_mode_a_renders(self, web_app_mod, monkeypatch):
        """模式 A 改写结果 — 不抛异常。"""
        state = _FakeSession()
        monkeypatch.setattr(web_app_mod.st, "session_state", state)
        # conftest 把 st.expander 设成 _identity_decorator（不是 ctx manager），
        # 临时替成 _StubEverything（conftest 已实现 __enter__/__exit__）
        from tests.conftest import _StubEverything
        monkeypatch.setattr(web_app_mod.st, "expander", lambda *a, **kw: _StubEverything())
        monkeypatch.setattr(web_app_mod.st, "container", lambda *a, **kw: _StubEverything())
        monkeypatch.setattr(web_app_mod.st, "spinner", lambda *a, **kw: _StubEverything())
        monkeypatch.setattr(web_app_mod.st, "status", lambda *a, **kw: _StubEverything())
        web_app_mod._render_rewrite_results({
            "mode": "A",
            "rewrites": [{
                "section": "experience_0", "original": "做产品",
                "rewritten": "负责产品规划，促成 200 单成交",
                "rewrite_reason": "对接 JD 销售转化能力",
            }],
            "warnings": [],
            "needs_user_review": True,
        })

    def test_mode_b_renders(self, web_app_mod, monkeypatch):
        """模式 B 生成结果 — 不抛异常。"""
        state = _FakeSession()
        monkeypatch.setattr(web_app_mod.st, "session_state", state)
        from tests.conftest import _StubEverything
        monkeypatch.setattr(web_app_mod.st, "expander", lambda *a, **kw: _StubEverything())
        monkeypatch.setattr(web_app_mod.st, "container", lambda *a, **kw: _StubEverything())
        monkeypatch.setattr(web_app_mod.st, "spinner", lambda *a, **kw: _StubEverything())
        monkeypatch.setattr(web_app_mod.st, "status", lambda *a, **kw: _StubEverything())
        web_app_mod._render_rewrite_results({
            "mode": "B",
            "rewrites": [{
                "section": "experience_0",
                "content": "月均获客 500-1000",
                "is_ai_generated": True,
                "anchored_keywords": ["获客", "增长"],
            }],
            "warnings": ["RAG 库数据为空"],
            "needs_user_review": True,
        })

    def test_empty_rewrites_no_crash(self, web_app_mod, monkeypatch):
        state = _FakeSession()
        monkeypatch.setattr(web_app_mod.st, "session_state", state)
        from tests.conftest import _StubEverything
        monkeypatch.setattr(web_app_mod.st, "expander", lambda *a, **kw: _StubEverything())
        web_app_mod._render_rewrite_results({
            "mode": "A", "rewrites": [], "warnings": [],
            "needs_user_review": False,
        })


# ============================================================
# helpers
# ============================================================

class _FakeSession(dict):
    def __getattr__(self, k):
        return self.get(k)
    def __setattr__(self, k, v):
        self[k] = v
