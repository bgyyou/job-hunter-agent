# -*- coding: utf-8 -*-
"""P0-008：简历库/JD 页面不得跨 user_id 回退到 "default"。

根因是"查不到当前用户的数据就退回共享账号"，多人共用同一个本机 SQLite 时
会把别人的简历/JD 展示或归属给当前账号。两处调用点各自扫描：
- pages/08：读侧回退（展示别人的简历）
- pages/03：写侧兜底（解析出的 JD 落到 "default" 名下）

配套的行为级隔离断言在 tests/unit/test_user_data_isolation.py。
"""
from __future__ import annotations

import re
from pathlib import Path

PAGES = Path(__file__).resolve().parents[2] / "pages"
HISTORY_PAGE = PAGES / "08_📈_Application_History.py"
STEP1_PAGE = PAGES / "03_📝_Flow_A_Step1.py"


class TestNoDefaultUserFallback:
    def test_history_page_has_no_default_literal(self):
        src = HISTORY_PAGE.read_text(encoding="utf-8")
        assert '"default"' not in src and "'default'" not in src, (
            "08 页出现 default 字面量 — 疑似 user_id 回退复活"
        )

    def test_history_page_does_not_call_list_resumes_directly(self):
        """db.list_resumes(...) 绕过 resume_library_service 的 user 作用域封装。"""
        src = HISTORY_PAGE.read_text(encoding="utf-8")
        assert "db.list_resumes(" not in src

    def test_history_page_shows_empty_state_guidance(self):
        src = HISTORY_PAGE.read_text(encoding="utf-8")
        assert re.search(r"st\.info\(\s*[\"']还没有任何简历", src), (
            "无简历时应给空态引导，而不是回退展示他人数据"
        )

    def test_step1_page_has_no_default_user_id_fallback(self):
        src = STEP1_PAGE.read_text(encoding="utf-8")
        assert 'user_id", "default"' not in src
        assert "current_user_id()" in src
