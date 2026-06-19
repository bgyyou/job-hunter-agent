# -*- coding: utf-8 -*-
"""Semantic chunker for JD text.

v2.1 M3.2: 按章节标题切分 JD，输出
- chunk_type ∈ {overview, responsibility, requirement, nice_to_have}
- heading_path ∈ [当前标题]，便于检索时上下文还原

为什么不做更细的句级切分：BGE-small-zh 上限 512 token，JD 段落普遍 < 200 字，
直接按 bullet/段落入 chunk 既能覆盖检索粒度，又保留语义连贯性。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Dict, List


CHUNK_TYPES = ("overview", "responsibility", "requirement", "nice_to_have")

# 标题 → chunk_type 映射；优先级按字典顺序匹配（先 nice_to_have，后 requirement）
_HEADING_PATTERNS: List[tuple] = [
    ("nice_to_have", re.compile(
        r"^\s*[•\-\*\d\.\)\(]*\s*"
        r"(加分项|优先考虑|优先|nice\s*to\s*have|bonus|preferred|plus|good\s*to\s*have)"
        r"[:：\s]*$", re.IGNORECASE)),
    ("responsibility", re.compile(
        r"^\s*[•\-\*\d\.\)\(]*\s*"
        r"(岗位职责|工作职责|工作内容|主要职责|职责描述|你将|你的工作|"
        r"responsibilities|what\s*you[' ]ll\s*do|key\s*responsibilities|the\s*role|"
        r"role\s*description|duties)"
        r"[:：\s]*$", re.IGNORECASE)),
    ("requirement", re.compile(
        r"^\s*[•\-\*\d\.\)\(]*\s*"
        r"(任职要求|岗位要求|招聘要求|任职资格|岗位资格|应聘条件|要求|"
        r"requirements|qualifications|required\s*skills|must\s*have|"
        r"who\s*you\s*are|what\s*we[' ]re\s*looking\s*for|skills?\s*&?\s*experience)"
        r"[:：\s]*$", re.IGNORECASE)),
    ("overview", re.compile(
        r"^\s*[•\-\*\d\.\)\(]*\s*"
        r"(关于公司|公司介绍|公司简介|about(\s*us)?|company\s*overview|"
        r"职位描述|岗位介绍|岗位描述|job\s*description|overview|summary|"
        r"about\s*the\s*role|about\s*the\s*job)"
        r"[:：\s]*$", re.IGNORECASE)),
]

_BULLET_PREFIX = re.compile(r"^\s*[•\-\*·▪◦‣⁃►▶]\s+|^\s*\d+[\.、\)）]\s+")


@dataclass
class Chunk:
    """One semantic unit extracted from a JD.

    Attributes:
        chunk_text: The text content (between ``MIN_CHUNK_LEN`` and ``MAX_CHUNK_LEN`` chars).
        chunk_type: One of ``CHUNK_TYPES`` — used for retrieval-time weighting.
        heading_path: Stack of heading lines that led here (currently single-level).
        keywords: Reserved for future TF-IDF style extraction; empty for now.
    """
    chunk_text: str
    chunk_type: str
    heading_path: List[str]
    keywords: List[str]

    def to_dict(self) -> Dict:
        """Serialize to a plain dict (suitable for ``insert_chunks_batch``)."""
        return asdict(self)


class SemanticChunker:
    """Section-aware JD text splitter.

    The chunker walks the input line by line, classifies each line as either
    a heading (mapped to one of ``CHUNK_TYPES``) or body text, then groups
    body text under the most recent heading into bullet- or paragraph-sized
    chunks. Long chunks are sentence-split to stay under ``MAX_CHUNK_LEN``.

    Why this granularity: BGE-small-zh has a 512-token window, JD bullets
    are typically <200 chars, so per-bullet chunks preserve semantic
    coherence without exceeding the encoder budget. Going finer (sentence-level)
    fragments meaning; going coarser (whole-section) loses retrieval precision.
    """

    MIN_CHUNK_LEN = 8       # Drop anything shorter (bullet residues, blank lines).
    MAX_CHUNK_LEN = 800     # Force sentence-split above this.

    def split(self, text: str) -> List[Chunk]:
        """Split JD text into ``Chunk`` objects.

        Returns ``[]`` for empty input. If the text has no recognizable
        headings AND is short, returns a single ``overview`` chunk as fallback.
        """
        if not text or not text.strip():
            return []

        lines = [ln.rstrip() for ln in text.splitlines()]
        sections: List[tuple] = []   # (chunk_type, heading, body_lines)
        current_type = "overview"
        current_heading = ""
        current_body: List[str] = []

        for ln in lines:
            stripped = ln.strip()
            if not stripped:
                current_body.append("")
                continue

            ct = self._match_heading(stripped)
            if ct is not None:
                # flush previous section
                if current_body:
                    sections.append((current_type, current_heading, current_body))
                current_type = ct
                current_heading = stripped
                current_body = []
            else:
                current_body.append(ln)

        if current_body:
            sections.append((current_type, current_heading, current_body))

        chunks: List[Chunk] = []
        for ct, heading, body in sections:
            heading_path = [heading] if heading else []
            for unit in self._split_body(body):
                clean = unit.strip()
                if len(clean) < self.MIN_CHUNK_LEN:
                    continue
                for piece in self._cap_length(clean):
                    chunks.append(Chunk(
                        chunk_text=piece,
                        chunk_type=ct,
                        heading_path=heading_path,
                        keywords=[],
                    ))

        # 兜底：完全没有标题且文本短 → 直接整段 overview
        if not chunks and text.strip():
            chunks.append(Chunk(
                chunk_text=text.strip()[: self.MAX_CHUNK_LEN],
                chunk_type="overview",
                heading_path=[],
                keywords=[],
            ))

        return chunks

    def _match_heading(self, line: str):
        """Return chunk_type if ``line`` matches a heading pattern, else ``None``.

        Lines longer than 40 chars are never treated as headings (long lines
        with verb phrases like "negotiate contracts and..." would false-match).
        """
        if len(line) > 40:
            return None
        for ct, pat in _HEADING_PATTERNS:
            if pat.match(line):
                return ct
        return None

    def _split_body(self, body: List[str]) -> List[str]:
        """Split a single section's body lines into discrete units.

        Bullet lines (``• item``, ``- item``, ``1. item``) become standalone units;
        contiguous non-bullet lines are joined into paragraph units; blank lines
        flush the paragraph buffer.
        """
        units: List[str] = []
        buf: List[str] = []

        def flush():
            if buf:
                joined = "\n".join(buf).strip()
                if joined:
                    units.append(joined)
                buf.clear()

        for ln in body:
            if _BULLET_PREFIX.match(ln):
                flush()
                # 把前缀去掉，留干净 bullet 文本
                cleaned = _BULLET_PREFIX.sub("", ln).strip()
                if cleaned:
                    units.append(cleaned)
            elif ln.strip() == "":
                flush()
            else:
                buf.append(ln)
        flush()
        return units

    def _cap_length(self, text: str) -> List[str]:
        """Sentence-split a too-long unit to keep each piece ≤ ``MAX_CHUNK_LEN``.

        Uses Chinese (``。！？``) and English (``.!?``) sentence terminators.
        Falls back to a hard char slice if no terminators are found.
        """
        if len(text) <= self.MAX_CHUNK_LEN:
            return [text]
        # 用中英文句号粗切
        parts = re.split(r"(?<=[。.!?！？])\s+", text)
        out: List[str] = []
        cur = ""
        for p in parts:
            if len(cur) + len(p) <= self.MAX_CHUNK_LEN:
                cur = (cur + " " + p).strip() if cur else p
            else:
                if cur:
                    out.append(cur)
                cur = p
        if cur:
            out.append(cur)
        return out or [text[: self.MAX_CHUNK_LEN]]
