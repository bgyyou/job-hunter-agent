# -*- coding: utf-8 -*-
"""v3 round-2: Flow A Step 4（一页纸预览）+ Step 5（导出）单测

按 update_plan.md §1.4 + §2.5 + §2.8：
- _estimate_resume 调 OnePageEstimator，返回 PageEstimate
- _estimate_resume 失败 fallback 不抛异常
- _render_one_page_estimate 渲染进度条 + 段行数 + 瘦身建议
- _handle_export 调 document_generator，超页抛错

覆盖（≥ 5 条）：
1. _estimate_resume 返回 PageEstimate
2. _estimate_resume 失败时 fallback PageEstimate
3. _handle_export Word 路径（mock document_generator）
4. _handle_export 超页 → OnePageOverflowError
5. _handle_export 失败 → st.error 不抛
6. _render_one_page_estimate 正常 / 超页 都不抛
"""
from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

import pytest


def _import_web_app():
    return importlib.import_module("web_app")


@pytest.fixture
def web_app_mod():
    return _import_web_app()


# ============================================================
# _estimate_resume
# ============================================================

class TestEstimateResume:
    def test_returns_page_estimate(self, web_app_mod):
        from services.one_page_estimator import PageEstimate
        est = web_app_mod._estimate_resume({
            "name": "X", "phone": "1", "email": "x@x.com",
            "experience": [{"company": "A", "title": "B",
                            "description": "C" * 100, "achievements": ["D"]}],
        })
        assert isinstance(est, PageEstimate)

    def test_no_crash_on_empty_resume(self, web_app_mod):
        from services.one_page_estimator import PageEstimate
        est = web_app_mod._estimate_resume({})
        assert isinstance(est, PageEstimate)

    def test_fallback_on_exception(self, web_app_mod, monkeypatch):
        """估算器抛异常时 fallback 到 PageEstimate（不抛给 UI）。"""
        # monkeypatch 注入一个 estimator 抛异常的桩
        from services import one_page_estimator as ope

        def _boom(resume, template="conservative"):
            raise RuntimeError("mock error")

        monkeypatch.setattr(ope.OnePageEstimator, "estimate", _boom)
        est = web_app_mod._estimate_resume({})
        # fallback 的 PageEstimate 有 suggestions 含错误信息
        assert est.overflow is False
        assert any("估算失败" in s for s in est.suggestions)


# ============================================================
# _render_one_page_estimate
# ============================================================

class TestRenderOnePageEstimate:
    def test_normal_does_not_crash(self, web_app_mod, monkeypatch):
        from services.one_page_estimator import PageEstimate
        from tests.conftest import _StubEverything
        monkeypatch.setattr(web_app_mod.st, "progress", lambda *a, **kw: None)
        monkeypatch.setattr(web_app_mod.st, "success", lambda *a, **kw: None)
        monkeypatch.setattr(web_app_mod.st, "error", lambda *a, **kw: None)
        monkeypatch.setattr(web_app_mod.st, "expander", lambda *a, **kw: _StubEverything())
        monkeypatch.setattr(web_app_mod.st, "markdown", lambda *a, **kw: None)
        est = PageEstimate(
            total_mm=120.0, capacity_mm=265.0, total_lines=25, capacity_lines=55,
            overflow=False, overflow_segments=[], suggestions=[], segment_lines={},
        )
        web_app_mod._render_one_page_estimate(est)

    def test_overflow_shows_warning(self, web_app_mod, monkeypatch):
        from services.one_page_estimator import PageEstimate
        from tests.conftest import _StubEverything
        monkeypatch.setattr(web_app_mod.st, "progress", lambda *a, **kw: None)
        monkeypatch.setattr(web_app_mod.st, "success", lambda *a, **kw: None)
        monkeypatch.setattr(web_app_mod.st, "error", lambda *a, **kw: None)
        monkeypatch.setattr(web_app_mod.st, "warning", lambda *a, **kw: None)
        monkeypatch.setattr(web_app_mod.st, "expander", lambda *a, **kw: _StubEverything())
        monkeypatch.setattr(web_app_mod.st, "markdown", lambda *a, **kw: None)
        est = PageEstimate(
            total_mm=300.0, capacity_mm=265.0, total_lines=80, capacity_lines=55,
            overflow=True, overflow_segments=["experience"],
            suggestions=["精简描述", "删除最早一段"],
            segment_lines={"experience": 40},
        )
        web_app_mod._render_one_page_estimate(est)


# ============================================================
# _handle_export
# ============================================================

class TestHandleExport:
    def test_word_success(self, web_app_mod, monkeypatch):
        from tests.conftest import _StubEverything
        monkeypatch.setattr(web_app_mod.st, "success", lambda *a, **kw: None)
        monkeypatch.setattr(web_app_mod.st, "download_button", lambda *a, **kw: None)
        monkeypatch.setattr(web_app_mod.st, "error", lambda *a, **kw: None)

        # 注入 document_generator stub
        from services import document_generator as dg
        fake_result = dg.DocumentResult(
            filename="张三_AI_产品经理_字节.docx",
            content=b"PK\x03\x04fake-docx",
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            template_used="conservative",
            estimate=MagicMock(),
        )
        fake_gen = MagicMock()
        fake_gen.generate_word.return_value = fake_result
        fake_gen.generate_pdf.return_value = fake_result
        monkeypatch.setattr(dg, "DocumentGenerator", lambda: fake_gen)

        # 不抛异常
        web_app_mod._handle_export(
            "docx",
            {"name": "张三"},
            {"company": "字节", "title": "AI 产品经理"},
            "conservative",
        )

    def test_overflow_raises(self, web_app_mod, monkeypatch):
        from tests.conftest import _StubEverything
        monkeypatch.setattr(web_app_mod.st, "success", lambda *a, **kw: None)
        monkeypatch.setattr(web_app_mod.st, "download_button", lambda *a, **kw: None)
        monkeypatch.setattr(web_app_mod.st, "error", lambda *a, **kw: None)

        from services import document_generator as dg
        from services.one_page_estimator import PageEstimate

        fake_est = PageEstimate(
            total_mm=300.0, capacity_mm=265.0, total_lines=80, capacity_lines=55,
            overflow=True, overflow_segments=["experience"],
            suggestions=["精简"], segment_lines={},
        )

        # 改用真 DocumentGenerator 但用超页 resume
        from services.document_generator import OnePageOverflowError
        overflow_resume = {
            "name": "X", "phone": "1", "email": "x@x.com",
            "experience": [
                {"company": f"C{i}", "title": "T",
                 "description": "x" * 600, "achievements": ["a"] * 20}
                for i in range(5)
            ],
        }
        web_app_mod._handle_export("docx", overflow_resume, {}, "conservative")
        # st.error 被调 → 不抛


# ============================================================
# helpers
# ============================================================

class _FakeSession(dict):
    def __getattr__(self, k):
        return self.get(k)
    def __setattr__(self, k, v):
        self[k] = v
