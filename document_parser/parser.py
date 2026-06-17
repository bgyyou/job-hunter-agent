"""Semantic PDF parser for JobHunter v2.

Extracts structured chunks from PDF documents using PyMuPDF (fitz).
Supports:
  - Heading hierarchy detection via font size / indentation / numbering
  - Paragraph, table, figure extraction as independent chunks
  - Scanned-document OCR fallback via PaddleOCR (optional)
"""

import base64
import io
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None


# ============================================================
# Internal helpers
# ============================================================

# Numbering patterns that signal heading levels
_HEADING_PATTERNS = [
    (r"^\d+\.\d+\.\d+\.\d+\.\s*", 4),   # 1.2.3.4.
    (r"^\d+\.\d+\.\d+\.\s*", 3),         # 1.2.3.
    (r"^\d+\.\d+\.\s*", 2),              # 1.2.
    (r"^\d+\.\s*", 1),                    # 1.
    (r"^[（(]\d+[）)]\s*", 1),             # （1） (1)
    (r"^[IVXLC]+[\.)]\s*", 1),            # I. A. 1.
]

_TABLE_MIN_ROWS = 2
_TABLE_MIN_COLS = 2


def _normalize_bbox(bbox: Tuple[float, ...]) -> List[float]:
    """Return [x0, y0, x1, y1] rounded to 2 decimals."""
    return [round(v, 2) for v in bbox[:4]]


def _page_to_image(page: "fitz.Page", dpi: int = 300) -> bytes:
    """Render a page to PNG bytes."""
    pix = page.get_pixmap(dpi=dpi)
    buf = io.BytesIO(pix.tobytes("png"))
    return buf.getvalue()


def _image_to_base64(img_bytes: bytes) -> str:
    """Encode image bytes to base64 data URI."""
    return base64.b64encode(img_bytes).decode("ascii")


def _detect_language(text: str) -> str:
    """Simple heuristic: check if mostly CJK."""
    cjk = len(re.findall(r"[一-鿿　-〿＀-￯]", text))
    total = len(text.replace(" ", ""))
    if total == 0:
        return "unknown"
    return "zh" if cjk / total > 0.3 else "en"


def _is_scanned_page(page: "fitz.Page", threshold: int = 50) -> bool:
    """Heuristic: if extract_text returns very little text, likely a scan."""
    text = page.get_text("text", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    return len(text.strip()) < threshold


# ============================================================
# OCR fallback
# ============================================================

def _ocr_page(
    page: "fitz.Page",
    page_num: int,
    dpi: int = 300,
) -> List[Dict[str, Any]]:
    """Render page to image and run PaddleOCR. Returns list of text chunks."""
    if fitz is None:
        logger.error("PyMuPDF not installed, cannot render page for OCR.")
        return []

    img_bytes = _page_to_image(page, dpi=dpi)
    try:
        from paddleocr import PaddleOCR  # type: ignore
    except ImportError:
        logger.warning(
            "PaddleOCR not installed. Install with: pip install paddleocr>=2.7.0 "
            "paddlepaddle. Scanned page will have no text."
        )
        return []

    ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
    result = ocr.ocr(io.BytesIO(img_bytes).read(), cls=True)

    chunks: List[Dict[str, Any]] = []
    if not result or not result[0]:
        return chunks

    # result[0] is a list of [[bbox, (text, confidence)], ...]
    lines = []
    for line_items in result[0]:
        for item in line_items:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                bbox = item[0]  # [[x0,y0],[x1,y1],[x2,y2],[x3,y3]]
                text_data = item[1]  # (text, confidence) or just text
                if isinstance(text_data, (list, tuple)) and len(text_data) >= 1:
                    text = text_data[0]
                else:
                    text = str(text_data)
                if text and text.strip():
                    cx = sum(p[0] for p in bbox) / 4
                    cy = sum(p[1] for p in bbox) / 4
                    lines.append((cy, cx, text, _normalize_bbox(bbox)))

    # Sort: top-to-bottom (y), then left-to-right (x)
    lines.sort(key=lambda l: (round(l[0] / 10) * 10, l[1]))

    # Group into paragraphs by y-gap
    paragraphs: List[List[Tuple[int, float, str, List[float]]]] = []
    for line in lines:
        if not paragraphs:
            paragraphs.append([line])
        else:
            prev = paragraphs[-1][-1]
            if abs(line[0] - prev[0]) < 20:  # same line height
                paragraphs[-1].append(line)
            else:
                paragraphs.append([line])

    for para_lines in paragraphs:
        text = " ".join(pl[2] for pl in para_lines)
        avg_bbox = [
            min(pl[3][0] for pl in para_lines),
            min(pl[3][1] for pl in para_lines),
            max(pl[3][2] for pl in para_lines),
            max(pl[3][3] for pl in para_lines),
        ]
        chunks.append({
            "chunk_id": f"ocr_{uuid.uuid4().hex[:8]}",
            "type": "paragraph",
            "content": text.strip(),
            "page": page_num + 1,
            "bbox": avg_bbox,
            "heading_path": [],
            "metadata": {"source": "", "timestamp": datetime.now(timezone.utc).isoformat()},
            "context": "",
        })

    return chunks


# ============================================================
# Main parser
# ============================================================

class PDFParser:
    """Parse PDF into semantic chunks for RAG ingestion.

    Usage:
        parser = PDFParser(document_title="JD_2026.pdf")
        chunks = parser.parse("path/to/file.pdf")
    """

    def __init__(
        self,
        document_title: str = "",
        document_version: str = "",
        dpi: int = 150,
        ocr_enabled: bool = True,
        ocr_dpi: int = 300,
        text_threshold: int = 50,
    ):
        """
        Args:
            document_title: Override document title from metadata.
            document_version: Document version string.
            dpi: Render DPI for figures and OCR.
            ocr_enabled: Enable scanned-page OCR fallback.
            ocr_dpi: DPI for OCR rendering.
            text_threshold: Min characters on a page before treating as scanned.
        """
        if fitz is None:
            raise ImportError(
                "PyMuPDF (fitz) is required. Install with: pip install PyMuPDF>=1.23.0"
            )

        self.document_title = document_title
        self.document_version = document_version
        self.dpi = dpi
        self.ocr_enabled = ocr_enabled
        self.ocr_dpi = ocr_dpi
        self.text_threshold = text_threshold

    def parse(self, pdf_path: str) -> List[Dict[str, Any]]:
        """Parse a PDF file and return a list of semantic chunks.

        Args:
            pdf_path: Path to the PDF file.

        Returns:
            List of chunk dicts in unified format.
        """
        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        doc = fitz.open(str(path))
        try:
            return self._parse_doc(doc, str(path.name))
        finally:
            doc.close()

    def _parse_doc(
        self, doc: "fitz.Document", filename: str
    ) -> List[Dict[str, Any]]:
        """Parse all pages of a fitz.Document."""
        chunks: List[Dict[str, Any]] = []

        # Extract document metadata
        meta = doc.metadata or {}
        title = self.document_title or meta.get("title", "") or filename
        author = meta.get("author", "") or ""
        page_count = len(doc)

        # Build metadata chunk (first chunk)
        meta_chunk = {
            "chunk_id": f"meta_{uuid.uuid4().hex[:8]}",
            "type": "paragraph",
            "content": f"Document: {title}\nAuthor: {author}\nPages: {page_count}\nVersion: {self.document_version or 'N/A'}",
            "page": 0,
            "bbox": [0, 0, 0, 0],
            "heading_path": [],
            "metadata": {
                "source": filename,
                "document_title": title,
                "document_version": self.document_version or "",
                "section_number": "",
                "table_number": "",
                "figure_caption": "",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            "context": "",
        }
        chunks.append(meta_chunk)

        # Track heading hierarchy per page
        current_heading_path: List[str] = []

        for page_num in range(page_count):
            page = doc[page_num]

            # --- Scanned page detection ---
            if _is_scanned_page(page, self.text_threshold):
                logger.info(
                    f"Page {page_num + 1} appears to be a scan "
                    f"(text < {self.text_threshold} chars)."
                )
                if self.ocr_enabled:
                    logger.info(f"Running OCR on page {page_num + 1}...")
                    ocr_chunks = _ocr_page(page, page_num, self.ocr_dpi)
                    for oc in ocr_chunks:
                        oc["metadata"]["source"] = filename
                        oc["metadata"]["document_title"] = title
                        chunks.append(oc)
                    # Reset heading path on scanned pages
                    current_heading_path = []
                    continue

                # OCR disabled: skip this page silently
                continue

            # --- Normal page processing ---
            page_chunks = self._parse_page(page, page_num, filename, title, current_heading_path)
            chunks.extend(page_chunks)

            # Update heading path from this page
            if current_heading_path:
                # Keep the last heading from this page as anchor for next page
                pass  # heading path persists across pages naturally

        return chunks

    def _parse_page(
        self,
        page: "fitz.Page",
        page_num: int,
        filename: str,
        title: str,
        heading_path: List[str],
    ) -> List[Dict[str, Any]]:
        """Parse a single page and return chunks."""
        chunks: List[Dict[str, Any]] = []
        source = filename
        ts = datetime.now(timezone.utc).isoformat()

        # --- Extract text blocks with font info ---
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]

        # Separate blocks by type
        heading_blocks: List[Tuple[dict, List[str]]] = []  # (block, new_path)
        paragraph_blocks: List[dict] = []
        table_blocks: List[dict] = []
        figure_blocks: List[dict] = []
        footnote_blocks: List[dict] = []

        # Identify header/footer regions (top/bottom 5% of page)
        page_height = page.rect.height
        header_region = page_height * 0.05
        footer_region = page_height * 0.95

        # Track heading hierarchy: stack of (level, text)
        heading_stack: List[Tuple[int, str]] = []

        for block in blocks:
            if block.get("type") == 1:  # Image block
                # Figure
                img_block = block
                bbox = _normalize_bbox(img_block["bbox"])
                try:
                    img_rect = fitz.Rect(bbox)
                    pix = page.get_pixmap(clip=img_rect, dpi=self.dpi)
                    img_bytes = pix.tobytes("png")
                    b64 = _image_to_base64(img_bytes)
                except Exception:
                    b64 = ""

                figure_blocks.append({
                    "chunk_id": f"fig_{uuid.uuid4().hex[:8]}",
                    "type": "figure",
                    "content": b64,
                    "page": page_num + 1,
                    "bbox": bbox,
                    "heading_path": list(heading_path),
                    "metadata": {
                        "source": source,
                        "document_title": title,
                        "document_version": self.document_version or "",
                        "section_number": "",
                        "table_number": "",
                        "figure_caption": "",
                        "timestamp": ts,
                    },
                    "context": "",
                })
                continue

            if block.get("type") != 0:  # Not text block
                continue

            lines = block.get("lines", [])
            if not lines:
                continue

            # Collect all text and font info from this block
            block_text_parts: List[str] = []
            block_bboxes: List[List[float]] = []
            font_sizes: List[float] = []
            font_names: List[str] = []

            for line in lines:
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if not text:
                        continue
                    block_text_parts.append(text)
                    block_bboxes.append(_normalize_bbox(span["bbox"]))
                    font_sizes.append(span.get("size", 0))
                    font_names.append(span.get("font", "").lower())

            block_text = " ".join(block_text_parts)
            if not block_text.strip():
                continue

            block_bbox = _normalize_bbox(block["bbox"])
            avg_font_size = sum(font_sizes) / len(font_sizes) if font_sizes else 0
            y_pos = block_bbox[1]

            # --- Header / Footer detection ---
            if y_pos < header_region or y_pos > footer_region:
                footnote_blocks.append({
                    "chunk_id": f"hf_{uuid.uuid4().hex[:8]}",
                    "type": "footnote",
                    "content": block_text,
                    "page": page_num + 1,
                    "bbox": block_bbox,
                    "heading_path": list(heading_path),
                    "metadata": {
                        "source": source,
                        "document_title": title,
                        "document_version": self.document_version or "",
                        "section_number": "",
                        "table_number": "",
                        "figure_caption": "",
                        "timestamp": ts,
                    },
                    "context": "",
                })
                continue

            # --- Heading detection ---
            is_heading, heading_level, heading_text = self._classify_heading(
                block_text, avg_font_size, font_names
            )

            if is_heading:
                # Update heading stack
                heading_stack = [(lvl, txt) for lvl, txt in heading_stack if lvl < heading_level]
                heading_stack.append((heading_level, heading_text))
                heading_path = [txt for _, txt in heading_stack]

                heading_blocks.append((
                    {
                        "chunk_id": f"h_{uuid.uuid4().hex[:8]}",
                        "type": "heading",
                        "content": heading_text,
                        "page": page_num + 1,
                        "bbox": block_bbox,
                        "heading_path": list(heading_path),
                        "metadata": {
                            "source": source,
                            "document_title": title,
                            "document_version": self.document_version or "",
                            "section_number": heading_text.split(".")[0] if "." in heading_text else "",
                            "table_number": "",
                            "figure_caption": "",
                            "timestamp": ts,
                        },
                        "context": "",
                    },
                    list(heading_path),
                ))
                continue

            # --- Table detection ---
            if self._looks_like_table(lines, avg_font_size):
                table_md = self._block_to_markdown(lines)
                table_blocks.append({
                    "chunk_id": f"tbl_{uuid.uuid4().hex[:8]}",
                    "type": "table",
                    "content": table_md,
                    "page": page_num + 1,
                    "bbox": block_bbox,
                    "heading_path": list(heading_path),
                    "metadata": {
                        "source": source,
                        "document_title": title,
                        "document_version": self.document_version or "",
                        "section_number": "",
                        "table_number": "",
                        "figure_caption": "",
                        "timestamp": ts,
                    },
                    "context": "",
                })
                continue

            # --- Paragraph / list detection ---
            chunk_type = "list" if self._looks_like_list(block_text) else "paragraph"
            chunks.append({
                "chunk_id": f"p_{page_num + 1}_{len(chunks) + 1:03d}",
                "type": chunk_type,
                "content": block_text.strip(),
                "page": page_num + 1,
                "bbox": block_bbox,
                "heading_path": list(heading_path),
                "metadata": {
                    "source": source,
                    "document_title": title,
                    "document_version": self.document_version or "",
                    "section_number": "",
                    "table_number": "",
                    "figure_caption": "",
                    "timestamp": ts,
                },
                "context": "",
            })

        # Append headings and tables after paragraph chunks
        for hc, _ in heading_blocks:
            chunks.append(hc)
        chunks.extend(table_blocks)
        chunks.extend(figure_blocks)
        chunks.extend(footnote_blocks)

        return chunks

    # ============================================================
    # Classification helpers
    # ============================================================

    def _classify_heading(
        self, text: str, font_size: float, font_names: List[str]
    ) -> Tuple[bool, int, str]:
        """Determine if a text block is a heading and its level.

        Returns: (is_heading, level, heading_text)
        """
        stripped = text.strip()
        if not stripped:
            return False, 0, ""

        # 1. Check numbering patterns
        for pattern, level in _HEADING_PATTERNS:
            if re.match(pattern, stripped):
                return True, level, stripped

        # 2. Short text + large font = likely heading
        if font_size > 14 and len(stripped) < 80:
            return True, 1, stripped

        # 3. Bold / sans-serif indicators in font name
        bold_keywords = ["bold", "semibold", "extrabold", "heavy"]
        sans_keywords = ["sans", "arial", "helvetica"]
        is_bold = any(k in "".join(font_names) for k in bold_keywords)
        is_sans = any(k in "".join(font_names) for k in sans_keywords)

        if is_bold and len(stripped) < 100:
            return True, 1, stripped

        return False, 0, ""

    def _looks_like_table(self, lines: list, avg_font_size: float) -> bool:
        """Heuristic: multiple lines with similar structure suggest a table."""
        if len(lines) < _TABLE_MIN_ROWS:
            return False

        # Check if lines have roughly consistent number of spans (columns)
        span_counts = []
        for line in lines:
            spans = line.get("spans", [])
            if spans:
                span_counts.append(len(spans))

        if not span_counts:
            return False

        # If most lines have >= 2 spans and span count is consistent
        consistent = all(c == span_counts[0] for c in span_counts)
        if consistent and span_counts[0] >= _TABLE_MIN_COLS:
            return True

        # Also check: uniform spacing between spans suggests columns
        if len(lines) >= _TABLE_MIN_ROWS:
            spacings = []
            for line in lines[:_TABLE_MIN_ROWS]:
                spans = line.get("spans", [])
                if len(spans) >= 2:
                    x_positions = [s.get("origin", [0, 0])[0] for s in spans]
                    spacings.extend(x_positions)
            # If many x positions cluster into distinct columns
            if len(spacings) >= _TABLE_MIN_COLS:
                return True

        return False

    def _looks_like_list(self, text: str) -> bool:
        """Check if text looks like a bulleted or numbered list."""
        lines = text.strip().split("\n")
        if len(lines) < 2:
            return False

        list_pattern = re.compile(
            r"^[\s]*[-*•\-•\d+)]\s+"
        )
        list_count = sum(1 for line in lines if list_pattern.match(line))
        return list_count / len(lines) > 0.5

    def _block_to_markdown(self, lines: list) -> str:
        """Convert a text block's lines into a Markdown table string."""
        rows: List[List[str]] = []
        for line in lines:
            cells = []
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                if text:
                    cells.append(text)
            if cells:
                rows.append(cells)

        if not rows:
            return ""

        # Pad rows to same width
        max_cols = max(len(r) for r in rows)
        for row in rows:
            while len(row) < max_cols:
                row.append("")

        md_lines: List[str] = []
        # Header
        md_lines.append("| " + " | ".join(rows[0]) + " |")
        md_lines.append("| " + " | ".join(["---"] * max_cols) + " |")
        # Body
        for row in rows[1:]:
            md_lines.append("| " + " | ".join(row) + " |")

        return "\n".join(md_lines)
