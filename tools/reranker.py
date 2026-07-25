# -*- coding: utf-8 -*-
"""本地 cross-encoder 精排 — BGE-reranker-base（568M 参数，~280MB）

P1-模块 5 实施（2026-07-25）：
- 在 vector_search top-N 之后、chunk_type × industry boost 之前插入
- cross-encoder 对 (query, chunk_text) 精确打分，输出 logits
- 失败/不可用 graceful fallback：原样返回，retrieval 不被打断
- 单例 lazy-load，跟 Embedder 一个模式
- 线程安全（ProcessPool/FastAPI 多 worker 下都安全）

设计决策（plan file polymorphic-otter § P1-模块 5 + 第一性原理）：
- 模型选择 BAAI/bge-reranker-base 而不是 v2-m3：用户 2026-07-24 决策（Q3）
  - 280MB 服务端内存可接受；延迟 50-200ms/1k 候选
  - 中文 query + 中文 JD 强相关
- RERANKER_ENABLED=false 时整模块短路（debug + 紧急回滚开关）
- 失败时 rerank_score=None，retrieval_service 走原来的 cosine × weights 路径
  - 永远不会出现"RAG 完全挂掉" — rerank 失败只是回退成原行为
"""
from __future__ import annotations

import math
import os
import threading
from typing import Any, Dict, List, Optional

from loguru import logger


_DEFAULT_MODEL = "BAAI/bge-reranker-base"


def _is_enabled() -> bool:
    """环境变量门：false 时绕过 rerank 整个模块（debug + 紧急回滚）。

    默认开。失败 fallback 不受此开关影响（fallback 是 reranker 内部的"self-disarm"）。
    """
    return os.environ.get("RERANKER_ENABLED", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _sigmoid(x: float) -> float:
    """logit → [0,1]。bge-reranker-base 输出 [~ -10, +10]，sigmoid 是经验最稳的归一化。"""
    try:
        return 1.0 / (1.0 + math.exp(-float(x)))
    except OverflowError:
        return 0.0 if x < 0 else 1.0


class CrossEncoderReranker:
    """Process-wide singleton — 封装 sentence_transformers.CrossEncoder。

    只在第一次 rerank() 时加载模型（lazy），跟 tools/embedder.py 同模式。
    """

    _instance: Optional["CrossEncoderReranker"] = None
    _lock = threading.Lock()
    _FAILED = "__failed__"  # 哨兵字符串，避免每次 _ensure_model 重试

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, model_name: Optional[str] = None):
        if getattr(self, "_initialized", False):
            return
        self.model_name = model_name or os.environ.get("RERANKER_MODEL", _DEFAULT_MODEL)
        self._model: Any = None
        self._initialized = True
        logger.info(
            f"CrossEncoderReranker initialized (lazy): model={self.model_name}, "
            f"enabled={_is_enabled()}"
        )

    def _ensure_model(self) -> bool:
        """首次调用时加载。失败后置 _FAILED（不要每次重试，浪费 +10s）。"""
        if self._model is not None and self._model != self._FAILED:
            return True
        if self._model == self._FAILED:
            return False

        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        try:
            from sentence_transformers import CrossEncoder  # type: ignore

            logger.info(
                f"Loading reranker: {self.model_name} (lazy, ~280MB, "
                f"HF_ENDPOINT={os.environ.get('HF_ENDPOINT')})"
            )
            self._model = CrossEncoder(self.model_name)
            logger.info("Reranker model loaded")
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"Reranker model load failed ({type(exc).__name__}): {exc}; "
                f"retrieval will fall back to cosine × weights path"
            )
            self._model = self._FAILED
            return False

    def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_k: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """用 cross-encoder 重排 candidates。

        Args:
            query: 用户原始查询（不做 embed，直接进 cross-encoder 拼对）。
            candidates: vector_search 输出的 dict 列表（每项必须含 chunk_text）。
            top_k: 如果设了，rerank 后只返回前 top_k；否则返回全部重排结果。

        Returns:
            重排后的 candidates 列表，每项多一个 ``rerank_score`` 字段。
            - 如果 RERANKER_ENABLED=false 或模型加载失败：返回 candidates 原样，
              不添加 rerank_score 字段。
            - top_k 是截断的语义，截断发生在重排之后。
        """
        if not _is_enabled():
            return list(candidates)
        if not candidates:
            return list(candidates)
        if not self._ensure_model():
            return list(candidates)

        pairs = [(query, str(c.get("chunk_text", "") or "")) for c in candidates]
        try:
            scores = self._model.predict(
                pairs,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"CrossEncoder.predict failed: {exc}; passing through unchanged"
            )
            return list(candidates)

        # 归一化到 [0,1] 后再 mix，比直接吃 logits 更稳
        scored = []
        for cand, raw in zip(candidates, scores):
            new_cand = dict(cand)
            raw_f = float(raw)
            new_cand["rerank_score"] = round(raw_f, 4)
            new_cand["rerank_score_norm"] = round(_sigmoid(raw_f), 4)
            scored.append(new_cand)

        scored.sort(key=lambda c: c.get("rerank_score", 0.0), reverse=True)

        if top_k is not None and top_k > 0:
            scored = scored[:top_k]
        return scored
