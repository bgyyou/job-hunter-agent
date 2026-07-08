# -*- coding: utf-8 -*-
"""Pytest fixtures for v2.1 M4 test suite.

提供：
- tmp_db: 临时 sqlite 后端，每个 test 一个独立 db 文件
- mock_embedder: 替换 tools.embedder.Embedder 为 deterministic 假向量，避免下载模型
- mock_llm_client: 提供 OpenAICompatibleClient 协议的 stub，无需真实 API
"""
from __future__ import annotations

import hashlib
import sys
import types
from pathlib import Path
from typing import Any, List

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Heavy-dep stubs (CI minimal-deps 兼容)
# ---------------------------------------------------------------------------
# 以下测试在 module 顶部 `import web_app`，web_app 顶部又会拉 streamlit →
# agents → tools → pymupdf / bs4 / fake_useragent / cryptography / playwright。
# CI 的 "minimal test deps" 明确排除 sentence-transformers / playwright 等重物，
# 但这两个测试只在跑纯函数 helpers（_jd_platform_label / _live_snapshot_from_db 等），
# 不会真渲染 UI，也不会真用 pymupdf 解析 PDF。
#
# 在 conftest 里把这些模块换成轻量 stub：import 能成功，调用都是 no-op。
# 这样 web_app 的导入链通了，CI 不用装重物。

class _StubEverything:
    """所有属性访问 / 调用都返回 self（或别的 _StubEverything），让 chain 不断。"""

    def __getattr__(self, name: str) -> Any:
        return _StubEverything()

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return _StubEverything()

    def __iter__(self):
        return iter([])

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __bool__(self):
        return False


def _install_stub(name: str, **attrs: Any) -> None:
    """在 sys.modules 里塞一个 name 的空模块，attrs 是顶层符号。"""
    if name in sys.modules:
        return
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


def _install_recursive_stub(name: str) -> None:
    """递归 stub：name.* 全部返回 _StubEverything。"""
    if name in sys.modules:
        return
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    # 让任何属性访问都返回 stub
    def _attr(k):
        sub_name = f"{name}.{k}"
        if sub_name not in sys.modules:
            sub = types.ModuleType(sub_name)
            sys.modules[sub_name] = sub
        return sub
    mod.__getattr__ = _attr  # type: ignore[attr-defined]


# Streamlit：UI 框架。web_app 在 module 顶部只调用 st.set_page_config / st.markdown，
# 都不会真渲染。其它属性/方法被访问时返回 _StubEverything()，链不断。
_streamlit_stub = _StubEverything()
# 一些常用的可调用装饰器/函数 — 让 cache_data 等装饰器直接返回原函数
def _identity_decorator(*a, **kw):
    def _dec(f):
        return f
    if a and callable(a[0]) and not kw:
        return a[0]
    return _dec
for _name in (
    "cache_data", "cache_resource", "cache", "spinner", "experimental_singleton",
    "set_page_config", "markdown", "write", "info", "warning", "error", "success",
    "button", "text_input", "text_area", "number_input", "selectbox", "multiselect",
    "checkbox", "radio", "slider", "file_uploader", "download_button", "form",
    "form_submit_button", "sidebar", "tab", "expander", "container",
    "empty", "stop", "rerun", "set_option", "session_state",
    "header", "subheader", "title", "code", "json", "dataframe", "table",
    "metric", "progress", "balloons", "snow", "toast", "status",
    "exception", "image", "video", "audio", "html",
):
    setattr(_streamlit_stub, _name, _identity_decorator)

# st.tabs(["a", "b"]) → [tab_a, tab_b]（list-like）
def _stub_tabs(labels):
    return [_StubEverything() for _ in labels]
_streamlit_stub.tabs = _stub_tabs
# st.columns(4) → [c1, c2, c3, c4]（list-like）
def _stub_columns(spec):
    if isinstance(spec, int):
        return [_StubEverything() for _ in range(spec)]
    return [_StubEverything() for _ in spec]
_streamlit_stub.columns = _stub_columns
# st.form("name") → context manager
_streamlit_stub.form = lambda *a, **kw: _StubEverything()
# session_state 是个 dict-like，单独再包一层
class _SessionState(dict):
    def __getattr__(self, k):
        return self.get(k)
    def __setattr__(self, k, v):
        self[k] = v
_streamlit_stub.session_state = _SessionState()

sys.modules.setdefault("streamlit", types.ModuleType("streamlit"))
sys.modules["streamlit"].__getattr__ = lambda k: getattr(_streamlit_stub, k)
# 直接 import streamlit 拿到的 namespace 也用 _streamlit_stub 的属性
import streamlit as _st  # noqa: E402
for _n in dir(_streamlit_stub):
    if not _n.startswith("_"):
        setattr(_st, _n, getattr(_streamlit_stub, _n))

# pymupdf / fitz：PDF 解析。测试不真解析 PDF，但 web_app 顶部 from tools.resume_parser 会拉它。
class _FakePage:
    def get_text(self):
        return ""
class _FakeDocument:
    def __iter__(self):
        return iter([])
    def __getitem__(self, i):
        return _FakePage()
    def close(self):
        pass
for _m in ("pymupdf", "fitz"):
    sys.modules.setdefault(_m, types.ModuleType(_m))
    setattr(sys.modules[_m], "open", lambda *a, **kw: _FakeDocument())
    setattr(sys.modules[_m], "Document", _FakeDocument)
# tools.resume_parser 里 `import pymupdf` 之后 pymupdf.open(pdf_path) 会被调用；
# 但纯 helper 测试不会触发 PDF 解析路径。

# bs4：HTML 解析。test 里不解析 HTML，但 web_app 链会拉。
class _FakeBeautifulSoup:
    def __init__(self, *a, **kw): pass
    def find(self, *a, **kw): return None
    def find_all(self, *a, **kw): return []
    def get_text(self, *a, **kw): return ""
sys.modules.setdefault("bs4", types.ModuleType("bs4"))
sys.modules["bs4"].BeautifulSoup = _FakeBeautifulSoup

# requests / httpx：HTTP 客户端。测试不发请求，但 web_app → tools.scraper 会拉。
class _FakeResponse:
    status_code = 200
    text = ""
    content = b""
    def json(self): return {}
    def raise_for_status(self): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False
def _fake_get(*a, **kw): return _FakeResponse()
def _fake_post(*a, **kw): return _FakeResponse()
def _fake_session(*a, **kw):
    s = _StubEverything()
    s.get = _fake_get
    s.post = _fake_post
    return s
for _m in ("requests", "httpx"):
    if _m not in sys.modules:
        mod = types.ModuleType(_m)
        mod.get = _fake_get
        mod.post = _fake_post
        mod.head = _fake_get
        mod.put = _fake_post
        mod.delete = _fake_get
        mod.Session = _fake_session
        mod.Response = _FakeResponse
        sys.modules[_m] = mod
# lxml: HTML 解析底层，bs4 警告链可能拉
if "lxml" not in sys.modules:
    sys.modules["lxml"] = types.ModuleType("lxml")
    sys.modules["lxml.html"] = types.ModuleType("lxml.html")

# fake_useragent：仅在 import 时构造 UserAgent 实例
class _FakeUserAgent:
    def random(self): return "Mozilla/5.0"
    chrome = "Mozilla/5.0"
    safari = "Mozilla/5.0"
    firefox = "Mozilla/5.0"
sys.modules.setdefault("fake_useragent", types.ModuleType("fake_useragent"))
sys.modules["fake_useragent"].UserAgent = lambda *a, **kw: _FakeUserAgent()

# cryptography：依赖链底层
# web_app 链里只用到 `from cryptography.fernet import Fernet`（cookie_manager）。
# 给 cryptography.fernet 一个真实的 Fernet stub，其它子模块 placeholder 即可。
class _FakeFernet:
    @staticmethod
    def generate_key():
        return b"a" * 44
    def __init__(self, key):
        self._key = key
    def encrypt(self, data):
        return data if isinstance(data, bytes) else data.encode("utf-8")
    def decrypt(self, token):
        return token
_fernet_mod = types.ModuleType("cryptography.fernet")
_fernet_mod.Fernet = _FakeFernet
sys.modules.setdefault("cryptography.fernet", _fernet_mod)
_crypto_mod = types.ModuleType("cryptography")
sys.modules.setdefault("cryptography", _crypto_mod)
_crypto_mod.fernet = _fernet_mod
# 其它 cryptography.* 子模块 placeholder（万一以后 chain 扩了）
for _sub in (
    "hazmat", "hazmat.primitives", "hazmat.primitives.asymmetric",
    "hazmat.primitives.serialization", "hazmat.primitives.hashes",
    "hazmat.backends", "hazmat.backends.openssl", "x509",
):
    if _sub not in sys.modules:
        sys.modules[_sub] = types.ModuleType(f"cryptography.{_sub}")

# playwright：web_app 链会拉 playwright.async_api，但测试不会真用
_install_recursive_stub("playwright")
_install_recursive_stub("playwright.async_api")
_install_recursive_stub("playwright.sync_api")
sys.modules["playwright.async_api"].async_playwright = _StubEverything()
sys.modules["playwright.async_api"].Browser = _StubEverything
sys.modules["playwright.async_api"].BrowserContext = _StubEverything
sys.modules["playwright.async_api"].Page = _StubEverything
sys.modules["playwright.async_api"].TimeoutError = type("PlaywrightTimeoutError", (Exception,), {})
sys.modules["playwright.sync_api"].sync_playwright = _StubEverything()




# ---------------------------------------------------------------------------
# 临时 SQLite 后端
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path):
    """每个 test 独立的 SqliteBackend 实例。"""
    from database.backends.sqlite_backend import SqliteBackend

    db_path = tmp_path / "test.db"
    backend = SqliteBackend(db_path=str(db_path))
    yield backend


# ---------------------------------------------------------------------------
# Mock Embedder：deterministic 8-d 向量，纯字符串哈希派生，离线、零依赖
# ---------------------------------------------------------------------------

class _FakeEmbedder:
    """模拟 BGE，提供 8 维 deterministic 向量。"""

    DIM = 8

    def __init__(self, *args, **kwargs):
        self.model_name = "fake-embedder"
        self._dim = self.DIM

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, text: str) -> List[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        out: List[List[float]] = []
        for t in texts:
            t = t or " "
            digest = hashlib.sha256(t.encode("utf-8")).digest()
            vec = [(b / 255.0) * 2 - 1 for b in digest[: self.DIM]]
            norm = sum(x * x for x in vec) ** 0.5 or 1.0
            out.append([x / norm for x in vec])
        return out


@pytest.fixture
def mock_embedder(monkeypatch):
    """patch tools.embedder.Embedder 为 _FakeEmbedder。"""
    import tools.embedder as embedder_mod
    monkeypatch.setattr(embedder_mod, "Embedder", _FakeEmbedder)
    # tools.jd_indexer 内是 from tools.embedder import Embedder（运行时才 import），所以 monkeypatch 即可
    return _FakeEmbedder


# ---------------------------------------------------------------------------
# Mock LLM client：暴露与 OpenAICompatibleClient 一样的最小接口
# ---------------------------------------------------------------------------

class _FakeLLMClient:
    """模拟 OpenAICompatibleClient，返回固定结构。"""

    def __init__(self, *args, **kwargs):
        self.model = "fake-llm"
        self.calls: list = []

    async def analyze(self, messages, max_tokens=4096, temperature=0.7, use_cache=True, system_prompt=None):
        from tools.llm import LLMResponse
        self.calls.append({"messages": messages, "system_prompt": system_prompt})
        return LLMResponse(
            content='{"score": 88, "reasoning": "fake match"}',
            model=self.model,
            tokens_used=42,
            finish_reason="stop",
        )

    async def analyze_with_structured_output(self, messages, output_schema, max_tokens=4096, temperature=0.7):
        self.calls.append({"messages": messages, "schema": output_schema})
        return {"score": 88, "reasoning": "fake structured"}


@pytest.fixture
def mock_llm_client():
    return _FakeLLMClient()
