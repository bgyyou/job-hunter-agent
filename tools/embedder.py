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
    """本地语义嵌入（单例）。"""

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
        self._ensure_model()
        return self._dim or _DEFAULT_DIM

    def embed(self, text: str) -> List[float]:
        """单条文本 → 归一化向量。"""
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        """批量文本 → 归一化向量列表。空文本返回零向量。"""
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
