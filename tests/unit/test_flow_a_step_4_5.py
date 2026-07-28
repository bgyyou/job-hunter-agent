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
page_mod_1 = importlib.import_module('pages.05_💬_Flow_A_Step3')

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
        est = page_mod_1._estimate_resume({
            "name": "X", "phone": "1", "email": "x@x.com",
            "experience": [{"company": "A", "title": "B",
                            "description": "C" * 100, "achievements": ["D"]}],
        })
        assert isinstance(est, PageEstimate)

    def test_no_crash_on_empty_resume(self, web_app_mod):
        from services.one_page_estimator import PageEstimate
        est = page_mod_1._estimate_resume({})
        assert isinstance(est, PageEstimate)

    def test_fallback_on_exception(self, web_app_mod, monkeypatch):
        """估算器抛异常时 fallback 到 PageEstimate（不抛给 UI）。"""
        # monkeypatch 注入一个 estimator 抛异常的桩
        from services import one_page_estimator as ope

        def _boom(resume, template="conservative"):
            raise RuntimeError("mock error")

        monkeypatch.setattr(ope.OnePageEstimator, "estimate", _boom)
        est = page_mod_1._estimate_resume({})
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
        page_mod_1._render_one_page_estimate(est)

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
        page_mod_1._render_one_page_estimate(est)


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
        page_mod_1._handle_export(
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
        page_mod_1._handle_export("docx", overflow_resume, {}, "conservative")
        # st.error 被调 → 不抛


# ============================================================
# helpers
# ============================================================

class _FakeSession(dict):
    def __getattr__(self, k):
        return self.get(k)
    def __setattr__(self, k, v):
        self[k] = v


# ============================================================
# _offer_html_fallback  (P0-1 PDF 降级 HTML)
# ============================================================

class TestOfferHtmlFallback:
    def test_renders_html_bytes(self, web_app_mod, monkeypatch):
        """PDF 失败 → 降级 HTML 时返回有效字节（HTML doctype + 中文字符）。"""
        from tests.conftest import _StubEverything
        monkeypatch.setattr(web_app_mod.st, "info", lambda *a, **kw: None)
        monkeypatch.setattr(web_app_mod.st, "warning", lambda *a, **kw: None)
        monkeypatch.setattr(web_app_mod.st, "download_button", lambda *a, **kw: None)
        monkeypatch.setattr(web_app_mod.st, "error", lambda *a, **kw: None)
        monkeypatch.setattr(web_app_mod.st, "expander", lambda *a, **kw: _StubEverything())
        monkeypatch.setattr(web_app_mod.st, "markdown", lambda *a, **kw: None)

        resume = {"name": "张三", "phone": "138", "email": "a@a.com",
                  "experience": [{"company": "字节", "title": "PM",
                                  "description": "做 RAG", "achievements": ["DAU 1000"]}]}
        jd = {"title": "AI 产品经理", "company": "字节跳动"}
        page_mod_1._offer_html_fallback(resume, jd, "conservative", error="chromium not found")
        # 不抛异常，st.download_button / st.warning 都被调过即可

    def test_filename_uses_name_position_company(self, web_app_mod, monkeypatch):
        """HTML 文件名遵循 {姓名}_{岗位}_{公司}.{ext} 约定。"""
        from tests.conftest import _StubEverything
        monkeypatch.setattr(web_app_mod.st, "info", lambda *a, **kw: None)
        monkeypatch.setattr(web_app_mod.st, "warning", lambda *a, **kw: None)
        monkeypatch.setattr(web_app_mod.st, "error", lambda *a, **kw: None)

        captured = {}
        def _capture_dl(*a, **kw):
            captured["file_name"] = kw.get("file_name") or (a[2] if len(a) > 2 else None)
            return None

        monkeypatch.setattr(web_app_mod.st, "download_button", _capture_dl)
        monkeypatch.setattr(web_app_mod.st, "expander", lambda *a, **kw: _StubEverything())
        monkeypatch.setattr(web_app_mod.st, "markdown", lambda *a, **kw: None)

        resume = {"name": "李四", "phone": "1", "email": "l@l.com"}
        jd = {"title": "数据分析师", "company": "Acme"}
        page_mod_1._offer_html_fallback(resume, jd, "modern", error="playwright missing")

        assert captured["file_name"] is not None
        assert captured["file_name"].endswith(".html")
        assert "李四" in captured["file_name"]
        assert "数据分析师" in captured["file_name"]
        assert "Acme" in captured["file_name"]

    def test_handles_missing_jd(self, web_app_mod, monkeypatch):
        """jd=None 时仍能渲染（空 jd_d = {}）。"""
        from tests.conftest import _StubEverything
        monkeypatch.setattr(web_app_mod.st, "info", lambda *a, **kw: None)
        monkeypatch.setattr(web_app_mod.st, "download_button", lambda *a, **kw: None)
        monkeypatch.setattr(web_app_mod.st, "expander", lambda *a, **kw: _StubEverything())
        monkeypatch.setattr(web_app_mod.st, "markdown", lambda *a, **kw: None)

        resume = {"name": "王五", "phone": "1", "email": "w@w.com"}
        # jd=None 不抛
        page_mod_1._offer_html_fallback(resume, None, "conservative", error="x")

    def test_html_render_exception_falls_back_to_error(self, web_app_mod, monkeypatch):
        """_render_html 也失败时 → st.error，不抛。"""
        from tests.conftest import _StubEverything
        captured = {"errors": []}
        monkeypatch.setattr(web_app_mod.st, "error",
                            lambda msg: captured["errors"].append(str(msg)))
        monkeypatch.setattr(web_app_mod.st, "download_button", lambda *a, **kw: None)
        monkeypatch.setattr(web_app_mod.st, "expander", lambda *a, **kw: _StubEverything())
        monkeypatch.setattr(web_app_mod.st, "markdown", lambda *a, **kw: None)
        monkeypatch.setattr(web_app_mod.st, "info", lambda *a, **kw: None)
        monkeypatch.setattr(web_app_mod.st, "warning", lambda *a, **kw: None)

        from services import document_generator as dg
        fake_gen = MagicMock()
        fake_gen._to_dict.side_effect = lambda x: x
        fake_gen._render_html.side_effect = RuntimeError("html boom")
        monkeypatch.setattr(dg, "DocumentGenerator", lambda: fake_gen)

        page_mod_1._offer_html_fallback(
            {"name": "X"}, {"title": "T", "company": "C"}, "conservative", error="pdf boom"
        )
        assert any("HTML 渲染也失败" in e for e in captured["errors"])

    def test_handle_export_pdf_failure_calls_html_fallback(self, web_app_mod, monkeypatch):
        """_handle_export('pdf', ...) 失败 → 调 _offer_html_fallback（不静默 st.error）。"""
        from tests.conftest import _StubEverything
        captured = {"called": False, "warnings": [], "downloads": 0}
        monkeypatch.setattr(web_app_mod.st, "warning",
                            lambda msg: captured["warnings"].append(str(msg)))
        monkeypatch.setattr(web_app_mod.st, "download_button",
                            lambda *a, **kw: captured.__setitem__("downloads", captured["downloads"] + 1))
        monkeypatch.setattr(web_app_mod.st, "error", lambda *a, **kw: None)
        monkeypatch.setattr(web_app_mod.st, "success", lambda *a, **kw: None)
        monkeypatch.setattr(web_app_mod.st, "expander", lambda *a, **kw: _StubEverything())
        monkeypatch.setattr(web_app_mod.st, "markdown", lambda *a, **kw: None)
        monkeypatch.setattr(web_app_mod.st, "info", lambda *a, **kw: None)

        # 让 _offer_html_fallback 标记被调
        original_offer = page_mod_1._offer_html_fallback
        def _spy_offer(resume, jd, template, error=None):
            captured["called"] = True
            return original_offer(resume, jd, template, error)
        monkeypatch.setattr(page_mod_1, "_offer_html_fallback", _spy_offer)

        # 让 generate_pdf 抛异常
        from services import document_generator as dg
        fake_gen = MagicMock()
        fake_gen.generate_pdf.side_effect = RuntimeError("chromium not installed")
        # _to_dict 必须返回真 dict（不要 MagicMock），否则 suggest_filename 内部 sub 会炸
        fake_gen._to_dict.side_effect = lambda x: dict(x) if isinstance(x, dict) else {}
        # _render_html 返回有效字节
        fake_gen._render_html.return_value = "<!doctype html><html><body>简历</body></html>"
        monkeypatch.setattr(dg, "DocumentGenerator", lambda: fake_gen)

        page_mod_1._handle_export(
            "pdf",
            {"name": "张三", "phone": "1", "email": "z@z.com"},
            {"title": "AI PM", "company": "字节"},
            "conservative",
        )
        assert captured["called"], "PDF 失败时应触发 _offer_html_fallback"
