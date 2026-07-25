# -*- coding: utf-8 -*-
"""P1-模块 5 单元测试 — CrossEncoderReranker。

不要求模型下载、不要求 GPU。CrossEncoder 用 mock 模拟，
覆盖：singleton / 禁用 / 加载失败 / 空列表 / 重排顺序 / sigmoid 归一化。
"""
from __future__ import annotations

import os
import sys
import types
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# conftest 把 streamlit stub 成 types.ModuleType（无 __file__），sentence_transformers
# 真 import 会拉 torch → torch init → inspect.getfile(streamlit) → TypeError。
# 测试不依赖真模型，全部 mock，把 sentence_transformers 提前塞一个最小骨架进 sys.modules，
# 这样 patch("sentence_transformers.CrossEncoder") 不再触发真包的 import chain。
if "sentence_transformers" not in sys.modules or not hasattr(
    sys.modules.get("sentence_transformers"), "CrossEncoder"
):
    _fake_st = types.ModuleType("sentence_transformers")
    class _FakeCrossEncoder:
        def __init__(self, *args, **kwargs):
            pass
        def predict(self, pairs, **kwargs):
            return np.zeros(len(pairs), dtype=np.float32)
    _fake_st.CrossEncoder = _FakeCrossEncoder
    sys.modules["sentence_transformers"] = _fake_st

import tools.reranker as reranker_mod
from tools.reranker import CrossEncoderReranker


@pytest.fixture(autouse=True)
def reset_reranker_singleton(monkeypatch):
    """每个测试独立 singleton（避免前一个测试的 lazy-loaded state 残留）"""
    monkeypatch.setattr(CrossEncoderReranker, "_instance", None)
    yield
    monkeypatch.setattr(CrossEncoderReranker, "_instance", None)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_returns_same_instance(self):
        a = CrossEncoderReranker()
        b = CrossEncoderReranker()
        assert a is b

    def test_model_name_env_override(self, monkeypatch):
        monkeypatch.setenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
        monkeypatch.setattr(CrossEncoderReranker, "_instance", None)
        r = CrossEncoderReranker()
        assert r.model_name == "BAAI/bge-reranker-v2-m3"


# ---------------------------------------------------------------------------
# Disabled / Passthrough
# ---------------------------------------------------------------------------


class TestDisabled:
    def test_disabled_returns_input_unchanged(self, monkeypatch):
        monkeypatch.setenv("RERANKER_ENABLED", "false")
        rows = [
            {"chunk_text": "a", "similarity": 0.5},
            {"chunk_text": "b", "similarity": 0.9},
        ]
        # ensure lazy model would NOT load
        with patch("sentence_transformers.CrossEncoder") as mock_ce:
            out = CrossEncoderReranker().rerank("q", rows)
        mock_ce.assert_not_called()
        assert out == rows
        # rerank_score 字段不存在于返回，说明真没跑 rerank
        for r in out:
            assert "rerank_score" not in r

    def test_empty_candidates_returns_empty(self):
        out = CrossEncoderReranker().rerank("q", [])
        assert out == []

    def test_disabled_keeps_input_order(self, monkeypatch):
        monkeypatch.setenv("RERANKER_ENABLED", "off")
        rows = [{"chunk_text": f"c{i}", "similarity": 1 - i * 0.1} for i in range(3)]
        out = CrossEncoderReranker().rerank("q", rows)
        assert [r["chunk_text"] for r in out] == ["c0", "c1", "c2"]


# ---------------------------------------------------------------------------
# Order / scores
# ---------------------------------------------------------------------------


class TestRerankOrder:
    @patch("sentence_transformers.CrossEncoder")
    def test_reorders_by_score(self, mock_ce):
        mock_inst = MagicMock()
        mock_inst.predict.return_value = np.array([0.1, 0.9, 0.4], dtype=np.float32)
        mock_ce.return_value = mock_inst

        cands = [
            {"chunk_text": "least",  "similarity": 0.6},
            {"chunk_text": "most",   "similarity": 0.3},  # cosine 低但 rerank 高
            {"chunk_text": "middle", "similarity": 0.8},
        ]
        out = CrossEncoderReranker().rerank("query", cands)
        # most 排第一
        assert [r["chunk_text"] for r in out] == ["most", "middle", "least"]

    @patch("sentence_transformers.CrossEncoder")
    def test_top_k_truncates(self, mock_ce):
        mock_inst = MagicMock()
        mock_inst.predict.return_value = np.array(
            [0.1, 0.9, 0.4, 0.7, 0.3], dtype=np.float32
        )
        mock_ce.return_value = mock_inst

        cands = [{"chunk_text": f"c{i}", "similarity": 0.5} for i in range(5)]
        out = CrossEncoderReranker().rerank("q", cands, top_k=2)
        assert len(out) == 2
        assert out[0]["chunk_text"] == "c1"  # rerank score 0.9
        assert out[1]["chunk_text"] == "c3"  # rerank score 0.7

    @patch("sentence_transformers.CrossEncoder")
    def test_adds_score_fields(self, mock_ce):
        mock_inst = MagicMock()
        mock_inst.predict.return_value = np.array([0.0], dtype=np.float32)
        mock_ce.return_value = mock_inst

        out = CrossEncoderReranker().rerank("q", [{"chunk_text": "x", "similarity": 0.5}])
        assert "rerank_score" in out[0]
        assert "rerank_score_norm" in out[0]
        # logit=0 → sigmoid=0.5
        assert out[0]["rerank_score_norm"] == 0.5


# ---------------------------------------------------------------------------
# Sigmoid normalization
# ---------------------------------------------------------------------------


class TestSigmoid:
    def test_zero(self):
        assert reranker_mod._sigmoid(0.0) == pytest.approx(0.5, abs=1e-9)

    def test_large_positive_saturates(self):
        # 1/(1+exp(-20)) = 0.9999999979388463，浮点不是精确 1.0
        assert reranker_mod._sigmoid(20.0) == pytest.approx(1.0, abs=1e-6)
        assert reranker_mod._sigmoid(20.0) > 0.9999

    def test_large_negative_saturates(self):
        # 1/(1+exp(+20)) = 2.06e-9，浮点不是精确 0.0
        assert reranker_mod._sigmoid(-20.0) == pytest.approx(0.0, abs=1e-6)
        assert reranker_mod._sigmoid(-20.0) < 0.0001

    def test_monotonic(self):
        # 重排前的归一化分数单调递增
        prev = -1.0
        for x in [-3, -1, 0, 1, 3]:
            v = reranker_mod._sigmoid(float(x))
            assert v > prev
            prev = v


# ---------------------------------------------------------------------------
# Graceful fallback
# ---------------------------------------------------------------------------


class TestModelLoadFailure:
    def test_failed_load_passes_through(self):
        """模拟 _ensure_model 返回 False（模型加载失败），retrieval 不被打断。"""
        with patch.object(
            CrossEncoderReranker, "_ensure_model", return_value=False
        ):
            rows = [{"chunk_text": "x", "similarity": 0.5}]
            out = CrossEncoderReranker().rerank("q", rows)
        assert out == rows
        assert "rerank_score" not in out[0]

    def test_predict_failure_passes_through(self):
        """模型装载成功但 predict 抛异常 → passthrough，retrieval 不挂。

        _model 是 __init__ 里赋值的实例属性（非类属性），不能 patch.object on class。
        直接在实例上覆盖 _model 绕过 _ensure_model 即可。
        """
        r = CrossEncoderReranker()
        bad_model = MagicMock()
        bad_model.predict.side_effect = RuntimeError("oom")
        r._model = bad_model
        rows = [{"chunk_text": "x", "similarity": 0.5}]
        out = r.rerank("q", rows)
        assert out == rows
        assert "rerank_score" not in out[0]  # noqa
