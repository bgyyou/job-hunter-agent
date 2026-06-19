# -*- coding: utf-8 -*-
"""Local embedding service — BGE-small-zh-v1.5 (512-dim)

v2.1 M3.1: 单例 Embedder，封装 sentence-transformers。
- 默认模型 BAAI/bge-small-zh-v1.5（中英文混排友好；~95MB；本地推理）
- 首次启动 sentence-transformers 自动从 HF Hub 下载到 ~/.cache/huggingface/
- 输出已 L2 归一化 → 余弦相似度可直接用点积计算
- 可用 EMBEDDING_MODEL 环境变量覆盖
"""
from __future__ import annotations

import os
import threading
from typing import List, Optional

from loguru import logger

_DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"
_DEFAULT_DIM = 512


class Embedder:
    """Process-wide singleton wrapping sentence-transformers BGE-small-zh-v1.5.

    The model is loaded lazily on the first ``embed`` / ``embed_batch`` /
    ``dim`` access — instantiating ``Embedder()`` is cheap and safe at import
    time. Subsequent ``Embedder()`` calls return the same instance.

    All output vectors are L2-normalized, so cosine similarity reduces to a
    dot product. Default dim = 512 (BGE-small-zh).

    Override the model with the ``EMBEDDING_MODEL`` env var, e.g. swap to
    ``BAAI/bge-m3`` (1024-dim, multilingual).
    """

    _instance: Optional["Embedder"] = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, model_name: Optional[str] = None):
        if getattr(self, "_initialized", False):
            return
        self.model_name = model_name or os.environ.get("EMBEDDING_MODEL", _DEFAULT_MODEL)
        self._model = None
        self._dim: Optional[int] = None
        self._initialized = True
        logger.info(f"Embedder initialized (lazy): model={self.model_name}")

    def _ensure_model(self):
        """Load the underlying SentenceTransformer on first use.

        On Chinese networks, sets ``HF_ENDPOINT=https://hf-mirror.com`` if
        unset, so that HuggingFace Hub downloads succeed without a VPN.
        """
        if self._model is not None:
            return
        # v2.1 M3.1: 国内访问 huggingface.co 经常超时，未配置时默认走镜像 hf-mirror.com
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

        from sentence_transformers import SentenceTransformer  # 延迟导入

        logger.info(
            f"Loading embedding model: {self.model_name} "
            f"(HF_ENDPOINT={os.environ.get('HF_ENDPOINT')}; 首次会下载 ~95MB)"
        )
        self._model = SentenceTransformer(self.model_name)
        # 探测维度
        probe = self._model.encode(["维度探测"], normalize_embeddings=True)
        self._dim = int(probe.shape[1])
        logger.info(f"Embedding model loaded, dim={self._dim}")

    @property
    def dim(self) -> int:
        """Output vector dimension (forces model load on first access)."""
        self._ensure_model()
        return self._dim or _DEFAULT_DIM

    def embed(self, text: str) -> List[float]:
        """Encode a single string into a unit-norm vector of length ``self.dim``."""
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        """Encode a batch of strings into unit-norm vectors.

        Empty / whitespace-only inputs are silently replaced with ``" "`` to
        keep the output length aligned with the input length (callers can rely
        on positional correspondence).

        Args:
            texts: Strings to embed.
            batch_size: Inner SentenceTransformer batch size; tune down on low-RAM hosts.

        Returns:
            ``len(texts)`` lists of floats, each of length ``self.dim``.
        """
        if not texts:
            return []
        self._ensure_model()
        cleaned = [t if (t and t.strip()) else " " for t in texts]
        vectors = self._model.encode(
            cleaned,
            batch_size=batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return vectors.tolist()
