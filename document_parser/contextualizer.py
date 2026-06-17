# -*- coding: utf-8 -*-
"""Contextualizer for JobHunter v2.

Generates rich context descriptions for RAG chunks using:
  1. Rule-based templates (default, zero-cost)
  2. LLM-enhanced generation (optional, configurable model)

Every chunk receives a non-empty context description.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger


# ============================================================
# Rule-based context template
# ============================================================

# Document type mapping from metadata fields
DOC_TYPE_MAP = {
    "resume": "个人简历",
    "cv": "个人简历",
    "jd": "职位描述",
    "job_description": "职位描述",
    "policy": "政策文件",
    "report": "研究报告",
    "manual": "操作手册",
    "guide": "指南文档",
    "presentation": "演示文稿",
    "slide": "演示文稿",
    "book": "书籍",
    "paper": "学术论文",
}

# Default template constants
MIN_CONTEXT_CHARS = 50
MAX_CONTEXT_CHARS = 150
ABSTRACT_TRUNC = 100  # 前 N 字符用于摘要


def _summarize_text(text: str, max_chars: int = ABSTRACT_TRUNC) -> str:
    """Extract first N chars, clean whitespace, truncate at sentence boundary."""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0].rsplit("。", 1)[0].rsplit("，", 1)[0].strip() + "…"


def _detect_doc_type(chunk: Dict[str, Any]) -> str:
    """Infer document type from chunk metadata."""
    meta = chunk.get("metadata", {}) or {}
    # Direct type field
    for key in ("document_type", "doc_type", "type"):
        if meta.get(key):
            return str(meta[key])
    # From title
    title = meta.get("document_title", "") or ""
    title_lower = title.lower()
    if any(k in title_lower for k in ["resume", "cv ", "简历", "简历 "]):
        return "个人简历"
    if any(k in title_lower for k in ["jd", "job description", "职位描述", "招聘 "]):
        return "职位描述"
    if any(k in title_lower for k in ["policy", "政策", "规定"]):
        return "政策文件"
    if any(k in title_lower for k in ["report", "报告"]):
        return "研究报告"
    return "文档内容"


def _chunk_type_label(chunk_type: str) -> str:
    """Map internal chunk type to user-friendly label."""
    labels = {
        "heading": "标题",
        "paragraph": "正文段落",
        "table": "表格",
        "figure": "图片",
        "footnote": "页眉页脚/脚注",
        "list": "列表项",
    }
    return labels.get(chunk_type, chunk_type)


def _build_rule_context(
    chunk: Dict[str, Any],
    chunks: List[Dict[str, Any]],
    idx: int,
    doc_type: str,
) -> str:
    """Generate context using rule-based template (50-150 chars)."""
    meta = chunk.get("metadata", {}) or {}
    heading_path = chunk.get("heading_path", []) or []
    chunk_type = chunk.get("type", "paragraph")
    content = chunk.get("content", "") or ""

    # Section location
    section_str = " / ".join(heading_path) if heading_path else "文档首页"

    # Neighboring context
    prev_chunk = chunks[idx - 1] if idx > 0 else None
    next_chunk = chunks[idx + 1] if idx < len(chunks) - 1 else None

    prev_abstract = _summarize_text(prev_chunk.get("content", "") or "") if prev_chunk else "无上文"
    next_abstract = _summarize_text(next_chunk.get("content", "") or "") if next_chunk else "无下文"

    context = (
        f'[文档类型] {doc_type} | '
        f'[章节定位] 位于\'{section_str}\'，'
        f'[内容类型] {_chunk_type_label(chunk_type)}，'
        f'[上文简介] {prev_abstract}，'
        f'[下文预告] {next_abstract}'
    )

    # Trim to [MIN, MAX] range if it exceeds
    if len(context) > MAX_CONTEXT_CHARS:
        # Shorten section_str and abstracts
        section_str = heading_path[-1] if heading_path else "文档首页"
        prev_abstract = _summarize_text(prev_chunk.get("content", "") or "", 30) if prev_chunk else "无"
        next_abstract = _summarize_text(next_chunk.get("content", "") or "", 30) if next_chunk else "无"
        context = (
            f"[文档类型] {doc_type} | "
            f"[章节] {section_str} | "
            f"[类型] {_chunk_type_label(chunk_type)} | "
            f"[上文] {prev_abstract} | "
            f"[下文] {next_abstract}"
        )

    # Safety: ensure non-empty
    if not context or len(context) < MIN_CONTEXT_CHARS:
        context = (
            f"[文档类型] {doc_type} | "
            f"[章节] {section_str} | "
            f"[类型] {_chunk_type_label(chunk_type)} | "
            f"[内容] {_summarize_text(content, 60)}"
        )

    return context


# ============================================================
# LLM-enhanced context (optional)
# ============================================================

def _build_llm_prompt(chunks_batch: List[Tuple[int, Dict[str, Any]]], doc_meta: Dict) -> str:
    """Build a single prompt for a batch of chunks to minimize API calls."""
    doc_type = _detect_doc_type(chunks_batch[0][1])
    doc_title = (doc_meta.get("document_title", "") or chunks_batch[0][1].get("metadata", {}).get("document_title", "未知文档"))

    lines = [
        f"你是一名招聘领域的专业文档分析师。请为以下 {len(chunks_batch)} 个文档片段生成简短的上下文说明。"
        f"文档标题：{doc_title}"
        f"文档类型：{doc_type}"
        ""
        "要求：",
        "1. 每段上下文 50-150 字",
        "2. 包含：文档类型、章节定位、前后片段摘要",
        "3. 格式：[文档类型] xxx | [章节定位] xxx | [上文简介] xxx | [下文预告] xxx",
        "4. 不要省略任何片段",
        ""
        "输入格式：每个片段一行，格式为 INDEX<TAB>HEADING_PATH<TAB>CHUNK_TYPE<TAB>CONTENT",
        ""
        "请输入 JSON 数组，每个元素包含 index 和 context 字段。"
        ""
        "示例：",
        '[{"index": 0, "context": "[文档类型] 职位描述 | [章节定位] 位于“技术总监” | [上文简介] 文档元数据 | [下文预告] 岗位职责描述"}, ...]',
        ""
        "现在处理以下片段：",
    ]

    for idx, chunk in chunks_batch:
        heading_path = chunk.get("heading_path", []) or []
        section_str = " / ".join(heading_path) if heading_path else "文档首页"
        chunk_type = chunk.get("type", "paragraph")
        content = _summarize_text(chunk.get("content", "") or "", 200)
        lines.append(f"{idx}\t{section_str}\t{chunk_type}\t{content}")

    return "\n".join(lines)


def _generate_llm_contexts(
    chunks: List[Dict[str, Any]],
    doc_meta: Dict,
    batch_size: int = 10,
) -> Dict[int, str]:
    """Generate contexts via LLM, processing chunks in batches."""
    # Try to import OpenAI-compatible client
    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        try:
            from openai import OpenAI as OpenAIClient  # type: ignore
            OpenAI = OpenAIClient
        except ImportError:
            logger.warning("openai package not installed. LLM-enhanced contextualizer unavailable. Using rule-based fallback.")
            return {}

    # Read config from environment
    api_key = os.environ.get("CONTEXTUALIZER_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("CONTEXTUALIZER_BASE_URL") or os.environ.get("OPENAI_API_BASE", "")
    model = os.environ.get("CONTEXTUALIZER_MODEL", "gpt-4o-mini")

    if not api_key:
        logger.warning("CONTEXTUALIZER_API_KEY not set. Skipping LLM-enhanced context generation.")
        return {}

    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url

    client = OpenAI(**client_kwargs)

    context_map: Dict[int, str] = {}

    # Process in batches
    for batch_start in range(0, len(chunks), batch_size):
        batch_end = min(batch_start + batch_size, len(chunks))
        batch_chunks = [(i, chunks[i]) for i in range(batch_start, batch_end)]

        prompt = _build_llm_prompt(batch_chunks, doc_meta)

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=2000,
                response_format={"type": "json_object"},
            )
            result_text = response.choices[0].message.content or ""

            # Parse JSON response
            try:
                results = json.loads(result_text)
                if isinstance(results, list):
                    for item in results:
                        if isinstance(item, dict) and "index" in item and "context" in item:
                            context_map[item["index"]] = item["context"]
                elif isinstance(results, dict) and "results" in results:
                    for item in results["results"]:
                        if isinstance(item, dict) and "index" in item and "context" in item:
                            context_map[item["index"]] = item["context"]
            except json.JSONDecodeError:
                logger.warning(f"LLM returned non-JSON for batch starting at {batch_start}. Falling back to rule-based.")
                continue

        except Exception as e:
            logger.warning(f"LLM context generation failed for batch {batch_start}: {e}. Falling back to rule-based.")
            continue

    return context_map


# ============================================================
# Main class
# ============================================================

class Contextualizer:
    """Generate context descriptions for RAG chunks.

    Strategy:
      1. LLM-enhanced (if MODEL + API_KEY configured)
      2. Rule-based template (always available, zero cost)
    """

    def __init__(self, mode: str = "auto"):
        """
        Args:
            mode: "auto" (LLM if configured, else rule), "llm", "rule".
        """
        self.mode = mode

    def generate_context(
        self,
        chunks: List[Dict[str, Any]],
        doc_meta: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Generate context for all chunks in-place and return them.

        Args:
            chunks: List of chunk dicts (as returned by PDFParser.parse).
            doc_meta: Optional document metadata (unused in rule mode).

        Returns:
            The same list with `context` field filled for every chunk.
        """
        if not chunks:
            return chunks

        doc_meta = doc_meta or {}

        # Determine effective mode
        effective_mode = self.mode
        if effective_mode == "auto":
            llm_available = bool(
                os.environ.get("CONTEXTUALIZER_API_KEY") or os.environ.get("OPENAI_API_KEY")
            )
            effective_mode = "llm" if llm_available else "rule"

        if effective_mode == "llm":
            llm_contexts = _generate_llm_contexts(chunks, doc_meta)
            if llm_contexts:
                for i, chunk in enumerate(chunks):
                    chunk["context"] = llm_contexts.get(i, _build_rule_context(chunk, chunks, i, _detect_doc_type(chunk)))
                logger.info(f"LLM-enhanced context generated for {len(llm_contexts)}/{len(chunks)} chunks.")
                return chunks
            logger.info("LLM generation produced no results, falling back to rule-based.")

        # Rule-based (always works)
        doc_type = _detect_doc_type(chunks[0])
        for i, chunk in enumerate(chunks):
            chunk["context"] = _build_rule_context(chunk, chunks, i, doc_type)

        logger.info(f"Rule-based context generated for {len(chunks)} chunks.")
        return chunks
