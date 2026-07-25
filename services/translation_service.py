# -*- coding: utf-8 -*-
"""跨语言召回支持：英文 chunk 翻译为中文。

背景（2026-07-25）：
- DB 99% 索引 chunks 来自 jobsdb (English source)，但中文查询占 50%+
- 选 A 方案：索引时把英文 chunk 翻译成中文，统一进 BGE-small-zh 向量空间
- 成本估算：~21,179 chunks × ~180 tokens = ~3.8M tokens ≈ $2 one-time
- 保留 original_text，UI / 评测仍可拿英文原文

设计决策：
- 用 LLM 而非专用翻译 API：复用现有 Agnes 通道，不增加 vendor
- 短文本 (<=400 chars) 单次调用；长文本分段以保证 token 上限不超
- LRU 缓存避免重复翻译（按 chunk_text hash）
- 失败 graceful fallback：标记 translated_at 留空，下次重试
- 异步并发：asyncio.Semaphore 限速
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
from typing import Dict, List, Optional, Tuple

from loguru import logger


MAX_CHARS_PER_REQUEST = 4000  # 中文 ~2000 tokens 上限，留余量
SHORT_PROMPT_THRESHOLD = 400  # 单次调用上限 chars

TRANSLATION_PROMPT = """你是一个中英双语技术翻译，专精 IT / 招聘 / 商业领域。

任务：把下面的英文文本翻译成中文。要求：
1. 保持原意，IT 术语保留英文（如 "API", "SQL", "React"）
2. 招聘 JD 里的角色名称、职位名称翻译成中文常见说法
3. 公司名、产品名、品牌名音译或保留英文
4. 列表 / bullet 格式保留
5. 长度与原文接近，不要扩写或缩写
6. 如果原文是 HTML 标签或 boilerplate（如 "Apply now"），只翻译可见文本

英文原文：
---
{text}
---

中文翻译："""


# ---------------------------------------------------------------------------
# 语言检测（启发式，无需调用 LLM）
# ---------------------------------------------------------------------------

_CJK_RE = re.compile(r"[一-鿿　-〿＀-￯]")


def detect_language(text: str) -> str:
    """轻量启发式语言检测：纯中文 / 纯英文 / 混合。

    Returns: 'zh' | 'en' | 'mixed'
    """
    if not text or len(text) < 20:
        return "mixed"  # 太短，保守判定 mixed（让后续逻辑决定）
    cjk = len(_CJK_RE.findall(text))
    total = len(text)
    cjk_ratio = cjk / total
    if cjk_ratio > 0.3:
        return "zh"
    if cjk_ratio < 0.05:
        return "en"
    return "mixed"


# ---------------------------------------------------------------------------
# 缓存（避免重复翻译）
# ---------------------------------------------------------------------------

class _TranslationCache:
    """进程内 LRU：translated_by_text[hash] = translated_text。"""

    def __init__(self, max_size: int = 5000):
        self._data: Dict[str, str] = {}
        self._max = max_size

    def key(self, text: str) -> str:
        return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]

    def get(self, text: str) -> Optional[str]:
        return self._data.get(self.key(text))

    def put(self, text: str, translated: str) -> None:
        if len(self._data) >= self._max:
            # 简单 FIFO eviction（够用，不是真的 LRU）
            self._data.pop(next(iter(self._data)))
        self._data[self.key(text)] = translated


_cache = _TranslationCache()


# ---------------------------------------------------------------------------
# 输出清理：MiniMax-M3 默认先写  思维链，后接最终答案
# ---------------------------------------------------------------------------

_THINKING_TAG_RE = re.compile(r"```[\s\S]*?```", re.DOTALL)
_FENCE_RE = re.compile(r"```[\s\S]*?```", re.DOTALL)


def _strip_thinking(content: str) -> str:
    """Strip MiniMax-M3 reasoning blocks. Supports both forms:
       1. ```thinking...``` (fenced code block)
       2.  textual reasoning tags
    """
    BT = "```"
    LBR = "<"
    RBR = ">"
    # Pass 1: strip ```fenced``` blocks
    start = 0
    while True:
        s = content.find(BT, start)
        if s == -1:
            break
        e = content.find(BT, s + 3)
        if e == -1:
            break
        candidate = (content[:s] + content[e + 3:]).strip()
        if not candidate:
            return content
        content = candidate
        start = 0
    # Pass 2: strip  ...  plain tags
    while True:
        s = content.find(LBR)
        if s == -1:
            return content
        e = content.find(RBR, s + 1)
        if e == -1:
            return content
        head = content[s + 1:e]
        if not head:
            return content
        # find matching   after the first ">"
        close = content.find(LBR + "/" + head + RBR, e + 1)
        if close == -1:
            return content
        content = (content[:s] + content[close + len(head) + 3:]).strip()
    return content


# ---------------------------------------------------------------------------
# LLM 翻译主流程
# ---------------------------------------------------------------------------


class ChunkTranslator:
    """异步翻译：英文 chunk → 中文。复用 tools.llm.OpenAICompatibleClient。"""

    def __init__(self, concurrency: int = 8):
        self.concurrency = concurrency
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        api_key = os.environ.get("LLM_API_KEY", "")
        base_url = os.environ.get("LLM_BASE_URL", "")
        if not api_key or not base_url:
            logger.warning("LLM_API_KEY / LLM_BASE_URL 未配置，翻译不可用")
            return None
        from tools.llm import OpenAICompatibleClient
        self._client = OpenAICompatibleClient(
            api_key=api_key,
            api_url=base_url,
            model=os.environ.get("LLM_MODEL", "agnes-2.0-flash"),
            use_anthropic_format=os.environ.get("LLM_USE_ANTHROPIC_FORMAT", "false").lower() == "true",
            user_id="chunk_translator",
        )
        return self._client

    async def translate_one(self, text: str) -> str:
        """单条翻译。返回中文；失败抛异常（让上层走 fallback）。"""
        cached = _cache.get(text)
        if cached is not None:
            return cached

        client = self._get_client()
        if client is None:
            raise RuntimeError("LLM client not configured")

        from tools.llm import LLMMessage

        # 长文本分段（按段落切）
        if len(text) > MAX_CHARS_PER_REQUEST:
            parts = self._split_long_text(text)
            translated_parts: List[str] = []
            for part in parts:
                translated_parts.append(await self._call_llm(client, part))
            translated = "".join(translated_parts)
        else:
            translated = await self._call_llm(client, text)

        _cache.put(text, translated)
        return translated

    async def _call_llm(self, client, text: str) -> str:
        from tools.llm import LLMMessage
        prompt = TRANSLATION_PROMPT.format(text=text)
        resp = await client.analyze(
            [LLMMessage(role="user", content=prompt)],
            max_tokens=2048,
            temperature=0.1,  # 翻译要稳定
        )
        content = (resp.content or "").strip()
        content = _strip_thinking(content)
        if not content:
            raise RuntimeError("LLM returned empty translation")
        return content

    @staticmethod
    def _split_long_text(text: str) -> List[str]:
        """按段落切长文本，避免单次超 token。"""
        paras = re.split(r"(\n\s*\n)", text)
        parts: List[str] = []
        cur = ""
        for p in paras:
            if len(cur) + len(p) > MAX_CHARS_PER_REQUEST and cur:
                parts.append(cur)
                cur = p
            else:
                cur += p
        if cur:
            parts.append(cur)
        return parts

    async def translate_batch(
        self, texts: List[str], on_done=None
    ) -> List[Tuple[str, Optional[str], Optional[str]]]:
        """并发翻译。

        Args:
            texts: 待翻译的英文文本列表
            on_done: 可选回调 (idx, translated) → None；用于进度回调

        Returns:
            list of (original, translated_or_None, error_or_None)
        """
        sem = asyncio.Semaphore(self.concurrency)

        async def _one(idx: int, t: str) -> Tuple[int, str, Optional[str], Optional[str]]:
            async with sem:
                try:
                    translated = await self.translate_one(t)
                    if on_done:
                        on_done(idx, translated)
                    return (idx, t, translated, None)
                except Exception as exc:  # noqa: BLE001
                    if on_done:
                        on_done(idx, None)
                    return (idx, t, None, str(exc))

        tasks = [_one(i, t) for i, t in enumerate(texts)]
        results = await asyncio.gather(*tasks)
        # 按原顺序返回 (original, translated, error)
        out = [None] * len(texts)
        for idx, orig, trans, err in results:
            out[idx] = (orig, trans, err)
        return out  # type: ignore[return-value]
