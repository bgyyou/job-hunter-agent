# -*- coding: utf-8 -*-
"""Pytest fixtures for v2.1 M4 test suite.

提供：
- tmp_db: 临时 sqlite 后端，每个 test 一个独立 db 文件
- mock_embedder: 替换 tools.embedder.Embedder 为 deterministic 假向量，避免下载模型
- mock_llm_client: 提供 VolcanoClient 协议的 stub，无需真实 API
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import List

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


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
# Mock LLM client：暴露与 VolcanoClient 一样的最小接口
# ---------------------------------------------------------------------------

class _FakeLLMClient:
    """模拟 VolcanoClient，返回固定结构。"""

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
