# -*- coding: utf-8 -*-
"""v2.1 M4.4: Embedder 单测（mock 模型，避免下载）。

策略：直接 patch tools.embedder.Embedder 的内部 _model + _ensure_model，
绕过 sentence-transformers，校验外部接口契约。
- embed / embed_batch dim 一致
- 单例语义
- 空文本不崩
- L2 归一化（mock 输出经过我们的归一化逻辑）
"""
from __future__ import annotations

import math
from typing import List

import pytest


# ---------------------------------------------------------------------------
# Helper：把 Embedder 的 _model 替换为可控 fake，避开真实模型加载
# ---------------------------------------------------------------------------

class _FakeST:
    """模拟 SentenceTransformer.encode：每条文本输出固定 8 维向量。"""

    def __init__(self, dim: int = 8):
        self._dim = dim

    def encode(self, texts, batch_size=32, normalize_embeddings=True,
               convert_to_numpy=True, show_progress_bar=False):
        import numpy as np
        out = []
        for i, t in enumerate(texts):
            # 用文本长度 + 索引派生确定向量
            base = [(len(t) + i + j) % 7 + 0.1 for j in range(self._dim)]
            if normalize_embeddings:
                norm = math.sqrt(sum(x * x for x in base)) or 1.0
                base = [x / norm for x in base]
            out.append(base)
        return np.asarray(out, dtype=np.float32)


@pytest.fixture
def fresh_embedder(monkeypatch):
    """重置单例并注入 fake 模型，避开 sentence-transformers 下载。"""
    import tools.embedder as emb_mod
    # 清掉单例
    monkeypatch.setattr(emb_mod.Embedder, "_instance", None, raising=False)

    real_init = emb_mod.Embedder.__init__

    def patched_init(self, model_name=None):
        real_init(self, model_name)
        self._model = _FakeST(dim=8)
        self._dim = 8

    monkeypatch.setattr(emb_mod.Embedder, "__init__", patched_init)
    # 把 _ensure_model 短路掉
    monkeypatch.setattr(emb_mod.Embedder, "_ensure_model", lambda self: None)
    return emb_mod.Embedder


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEmbedderContract:
    def test_dim_property(self, fresh_embedder):
        e = fresh_embedder()
        assert e.dim == 8

    def test_embed_single_returns_list(self, fresh_embedder):
        e = fresh_embedder()
        v = e.embed("AI 产品")
        assert isinstance(v, list)
        assert len(v) == 8
        assert all(isinstance(x, float) for x in v)

    def test_embed_batch_dim_consistent(self, fresh_embedder):
        e = fresh_embedder()
        vecs = e.embed_batch(["a", "bb", "ccc"])
        assert len(vecs) == 3
        assert all(len(v) == 8 for v in vecs)

    def test_empty_string_handled(self, fresh_embedder):
        """空字符串内部会替换为空格再 encode，不应抛错。"""
        e = fresh_embedder()
        v = e.embed("")
        assert len(v) == 8

    def test_empty_list_returns_empty(self, fresh_embedder):
        e = fresh_embedder()
        assert e.embed_batch([]) == []

    def test_l2_normalized(self, fresh_embedder):
        e = fresh_embedder()
        v = e.embed("normalize me")
        n = math.sqrt(sum(x * x for x in v))
        assert abs(n - 1.0) < 1e-3

    def test_singleton(self, fresh_embedder):
        a = fresh_embedder()
        b = fresh_embedder()
        assert a is b
