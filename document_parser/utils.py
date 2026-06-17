# -*- coding: utf-8 -*-
"""Shared utilities for document_parser modules.

No extra dependencies — only stdlib + fitz (optional).
"""

import base64
import io
import re
from typing import Any, Dict, List, Optional, Tuple


# ============================================================
# Chunk ID generation
# ============================================================

def generate_chunk_id(
    source: str,
    page: int,
    seq: int,
    chunk_type: str = "",
) -> str:
    """Generate a deterministic unique chunk ID.

    Format: {prefix}_{source_basename}_{page}_{seq:04d}

    Args:
        source: File name (e.g. "JD_2026.pdf").
        page: 1-based page number.
        seq: Sequential index within the page.
        chunk_type: Short type hint (e.g. "tbl", "fig", "h").

    Returns:
        e.g. "h_JD_2026_1_0003"
    """
    import uuid
    # Use basename to strip path
    basename = source.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    # Strip extension
    name = basename.rsplit(".", 1)[0]
    prefix = chunk_type or "c"
    return f"{prefix}_{name}_{page}_{seq:04d}"


# ============================================================
# Coordinate helpers
# ============================================================

def normalize_bbox(bbox: Tuple[float, ...]) -> List[float]:
    """Return absolute [x0, y0, x1, y1] rounded to 2 decimals."""
    return [round(v, 2) for v in bbox[:4]]


def normalize_bbox_relative(
    bbox: Tuple[float, ...],
    page_width: float,
    page_height: float,
) -> List[float]:
    """Convert bbox to 0~1 relative coordinates.

    Args:
        bbox: [x0, y0, x1, y1] absolute coordinates.
        page_width: Page width in points (72 points = 1 inch).
        page_height: Page height in points.

    Returns:
        [x0_rel, y0_rel, x1_rel, y1_rel] each in [0, 1].
    """
    if page_width <= 0 or page_height <= 0:
        return [0.0, 0.0, 0.0, 0.0]
    return [
        round(bbox[0] / page_width, 4),
        round(bbox[1] / page_height, 4),
        round(bbox[2] / page_width, 4),
        round(bbox[3] / page_height, 4),
    ]


# ============================================================
# Image helpers
# ============================================================

def crop_and_encode(
    page,  # fitz.Page
    bbox: Tuple[float, ...],
    dpi: int = 150,
) -> Optional[str]:
    """Crop a region from a PDF page and return as base64 data URI.

    Args:
        page: fitz.Page instance.
        bbox: [x0, y0, x1, y1] crop region.
        dpi: Render resolution.

    Returns:
        e.g. "data:image/png;base64,iVBOR..." or None on error.
    """
    try:
        import fitz  # type: ignore
    except ImportError:
        return None

    try:
        img_rect = fitz.Rect(bbox[:4])
        pix = page.get_pixmap(clip=img_rect, dpi=dpi)
        img_bytes = pix.tobytes("png")
    except Exception:
        return None

    b64 = base64.b64encode(img_bytes).decode("ascii")
    return f"data:image/png;base64,{b64}"


def page_to_base64(
    page,  # fitz.Page
    dpi: int = 300,
) -> Optional[str]:
    """Render an entire page to base64 PNG data URI."""
    try:
        import fitz  # type: ignore
    except ImportError:
        return None

    try:
        pix = page.get_pixmap(dpi=dpi)
        img_bytes = pix.tobytes("png")
    except Exception:
        return None

    b64 = base64.b64encode(img_bytes).decode("ascii")
    return f"data:image/png;base64,{b64}"


# ============================================================
# Text cleaning
# ============================================================

# Characters that are commonly garbled from PDF extraction
_GARBLED_CHARS_RE = re.compile(
    "["
    "\x00-\x08\x0b\x0c\x0e-\x1f"  # control chars (keep \t, \n, \r)
    "�"                       # replacement char (U+FFFD)
    "]+",
)


def clean_text(text: str) -> str:
    """Clean extracted text from PDF artifacts.

    - Removes control characters and null bytes
    - Collapses multiple blank lines into one
    - Strips leading/trailing whitespace
    - Preserves CJK, Latin, common punctuation

    Args:
        text: Raw text from PyMuPDF.

    Returns:
        Cleaned text.
    """
    if not text:
        return ""

    # Remove control characters (keep newline, tab, form feed)
    text = _GARBLED_CHARS_RE.sub(" ", text)

    # Replace common PDF artifact: word + zero-width space + next word
    text = text.replace("​", "")  # zero-width space
    text = text.replace("­", "")  # soft hyphen

    # Collapse multiple whitespace / blank lines
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def truncate_sentence(text: str, max_chars: int) -> str:
    """Truncate text at a sentence boundary (中文句号 or period).

    Args:
        text: Source text.
        max_chars: Maximum length before truncation.

    Returns:
        Text truncated to ~max_chars, ending at nearest sentence boundary.
    """
    if not text or len(text) <= max_chars:
        return text

    truncated = text[:max_chars]
    # Find last sentence boundary
    for sep in ["。", ".", "！", "!", "?", "\n"]:
        idx = truncated.rfind(sep)
        if idx > max_chars // 3:
            return truncated[: idx + 1]

    return truncated + "…"


def summarize_excerpt(text: str, max_words: int = 30) -> str:
    """Take the first N words (by whitespace split) as a short excerpt.

    Useful for building context summaries.
    """
    if not text:
        return ""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "…"


# ============================================================
# Metadata helpers
# ============================================================

def build_metadata(
    source: str,
    title: str = "",
    version: str = "",
    chunk_type: str = "",
) -> Dict[str, str]:
    """Build a standardized metadata dict for a chunk.

    All fields default to '' rather than None for consistency.
    """
    import uuid
    return {
        "source": source,
        "document_title": title,
        "document_version": version,
        "chunk_type": chunk_type,
        "section_number": "",
        "table_number": "",
        "figure_caption": "",
        "figure_description": "",
        "timestamp": "",
        "_id": uuid.uuid4().hex[:8],
    }
