# -*- coding: utf-8 -*-
"""P0-007：用户自由文本输入长度上限。

两层防线各自单测：
1. `clamp_user_text` — 服务端截断，真防线（`max_chars` 是浏览器端约束，可绕过）
2. 页面 widget 带 `max_chars` + 提交路径调用 `clamp_user_text` — 静态扫描确认接线没漏
"""
from __future__ import annotations

from pathlib import Path

import pytest

from services.text_limits import MAX_USER_TEXT_CHARS, clamp_user_text

PAGES = Path(__file__).resolve().parents[2] / "pages"

# 三个"用户粘贴自由文本 → LLM"的入口
PASTE_ENTRY_PAGES = [
    "03_📝_Flow_A_Step1.py",
    "06_📄_Flow_B.py",
    "07_📚_JD_Library.py",
]


class TestClampUserText:
    def test_limit_is_20000(self):
        assert MAX_USER_TEXT_CHARS == 20000

    def test_short_text_untouched(self):
        text, truncated = clamp_user_text("岗位职责：负责 AI 产品规划")
        assert text == "岗位职责：负责 AI 产品规划"
        assert truncated is False

    def test_exactly_at_limit_not_truncated(self):
        text, truncated = clamp_user_text("字" * MAX_USER_TEXT_CHARS)
        assert len(text) == MAX_USER_TEXT_CHARS
        assert truncated is False

    def test_over_limit_is_truncated(self):
        text, truncated = clamp_user_text("字" * 50000)
        assert len(text) == MAX_USER_TEXT_CHARS
        assert truncated is True

    @pytest.mark.parametrize("empty", [None, ""])
    def test_empty_input_returns_empty_string(self, empty):
        assert clamp_user_text(empty) == ("", False)


class TestPagesWired:
    @pytest.mark.parametrize("page", PASTE_ENTRY_PAGES)
    def test_text_area_declares_max_chars(self, page):
        src = (PAGES / page).read_text(encoding="utf-8")
        for block in src.split("st.text_area(")[1:]:
            head = block[:400]
            assert "max_chars=MAX_USER_TEXT_CHARS" in head, (
                f"{page} 有 st.text_area 未声明 max_chars"
            )

    @pytest.mark.parametrize("page", PASTE_ENTRY_PAGES)
    def test_submit_path_calls_clamp(self, page):
        src = (PAGES / page).read_text(encoding="utf-8")
        assert "from services.text_limits import" in src
        assert "clamp_user_text(" in src, f"{page} 提交路径未做服务端截断"
