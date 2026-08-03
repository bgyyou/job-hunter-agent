"""Regression guards for the shared reasoning-block cleaner."""
from __future__ import annotations

import ast
from pathlib import Path

from services import translation_service
from services._text_utils import strip_thinking


ROOT = Path(__file__).resolve().parents[2]


def test_strip_thinking_removes_reasoning_tags():
    assert strip_thinking("<think>reasoning</think>最终答案") == "最终答案"


def test_translation_service_does_not_define_strip_thinking():
    assert not hasattr(translation_service, "_strip_thinking")


def test_debug_script_imports_shared_strip_thinking():
    source = (ROOT / "debug_cached_response.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert any(
        isinstance(node, ast.ImportFrom)
        and node.module == "services._text_utils"
        and any(alias.name == "strip_thinking" for alias in node.names)
        for node in ast.walk(tree)
    )
