# -*- coding: utf-8 -*-
"""JobHunter v2 document parser package.

Usage:
    from document_parser import PDFParser, Contextualizer, MultimodalDescriber
    parser = PDFParser(document_title="JD.pdf")
    chunks = parser.parse("path/to/file.pdf")
    ctx = Contextualizer()
    chunks = ctx.generate_context(chunks)
    describer = MultimodalDescriber()
    chunks = describer.describe_figures(chunks)
"""

from document_parser.parser import PDFParser
from document_parser.contextualizer import Contextualizer
from document_parser.multimodal import MultimodalDescriber

__all__ = ["PDFParser", "Contextualizer", "MultimodalDescriber"]
