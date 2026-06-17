# -*- coding: utf-8 -*-
"""MultimodalDescriber for JobHunter v2.

Uses a multimodal LLM (e.g. GPT-4o) to generate text descriptions
for figure-type chunks extracted from PDFs.
"""

import os
from typing import Any, Dict, List, Optional

from loguru import logger


# ============================================================
# Main class
# ============================================================

class MultimodalDescriber:
    """Generate text descriptions for figure chunks using a multimodal LLM.

    All API calls use an OpenAI-compatible interface.
    """

    def __init__(self, model: Optional[str] = None):
        """
        Args:
            model: Override MULTIMODAL_MODEL env var. Defaults to 'gpt-4o'.
        """
        self.model = model or os.environ.get("MULTIMODAL_MODEL", "gpt-4o")

    def describe_figures(
        self,
        chunks: List[Dict[str, Any]],
        model: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Describe all figure-type chunks and write results into metadata.

        Args:
            chunks: Chunk list (same list as returned by PDFParser.parse).
            model: Optional model override.

        Returns:
            The same list with metadata.figure_description filled for
            every figure chunk. Non-figure chunks are untouched.
        """
        figure_chunks = [c for c in chunks if c.get("type") == "figure"]
        if not figure_chunks:
            logger.info("No figure chunks found, skipping multimodal description.")
            return chunks

        effective_model = model or self.model

        # Lazy import — only when there are figures to describe
        try:
            from openai import OpenAI  # type: ignore
        except ImportError:
            logger.warning("openai package not installed. Figure description skipped.")
            return chunks

        # Get API key from env
        api_key = os.environ.get("MULTIMODAL_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            logger.warning("MULTIMODAL_API_KEY / OPENAI_API_KEY not set. Figure description skipped.")
            return chunks

        base_url = os.environ.get("MULTIMODAL_BASE_URL") or os.environ.get("OPENAI_API_BASE", "")
        client_kwargs: Dict[str, Any] = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url

        client = OpenAI(**client_kwargs)

        described = 0
        skipped = 0

        for chunk in figure_chunks:
            content = chunk.get("content", "") or ""
            if not content:
                logger.debug(f"Figure at page {chunk.get('page', '?')} has no image data, skipping.")
                chunk.setdefault("metadata", {})["figure_description"] = "[无图片数据]"
                skipped += 1
                continue

            try:
                # Content is a base64 data URI; strip prefix to get raw base64
                raw_b64 = content
                if content.startswith("data:"):
                    raw_b64 = content.split(",", 1)[1]

                response = client.chat.completions.create(
                    model=effective_model,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "你是一名招聘文档分析师。请用 1-2 句话描述这张图片的内容，"
                                "如果图片包含文字信息（如流程图、组织架构图、技能要求图），"
                                "请用中文总结关键内容。如果图片与招聘/职位描述无关，"
                                "简要说明图片类型即可。输出纯文本，不要 JSON。"
                            ),
                        },
                        {
                            "role": "user",
                            "content": [
                                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{raw_b64}"}},
                            ],
                        },
                    ],
                    max_tokens=300,
                    temperature=0.2,
                )
                description = response.choices[0].message.content or ""
                chunk.setdefault("metadata", {})["figure_description"] = description.strip()
                described += 1

            except Exception as e:
                logger.warning(f"Failed to describe figure (page {chunk.get('page', '?')}): {e}")
                chunk.setdefault("metadata", {})["figure_description"] = f"[描述失败: {e}]"
                skipped += 1

        logger.info(
            f"Figure description done: {described} described, {skipped} skipped "
            f"out of {len(figure_chunks)} figure chunks."
        )
        return chunks
