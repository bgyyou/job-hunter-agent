"""R4 红线兜底：README 不准许跟代码现状对不上的功能描述。

P0-003 关闭后必须保持。每条对应 owner 2026-08-03 Q3 决议的一项裂缝。
"""
from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
README = PROJECT_ROOT / "README.md"
readme_text = README.read_text(encoding="utf-8")


def _section(text: str, start: str, end: str = "\n\n") -> str:
    s = text.find(start)
    if s < 0:
        return ""
    e = text.find(end, s)
    return text[s:e if e > 0 else s + len(start)]


class TestReadmeNoLyingFeatures:
    """README "主要功能" 表与 "爬虫" 节必须和代码现状对齐（P0-003）。"""

    def test_no_chat_assistant_sidebar_widget(self):
        """README 不能宣传 "AI 求职助手 / 侧栏浮窗" —— web_app.py 已 display:none 整个 sidebar。"""
        assert "AI 求职助手" not in readme_text, (
            "README 仍含 'AI 求职助手' 描述，但代码层 chat_assistant 未被任何 page 调用"
        )
        assert "侧栏浮窗" not in readme_text, (
            "README 仍含 '侧栏浮窗'，需改写或删除（web_app.py:70-78 显式 display:none）"
        )

    def test_no_user_adopted_or_accept_button(self):
        """README 不能宣传 "采纳优化建议 / 落 user_adopted" —— backend 方法存在但无 UI 入口。"""
        assert "user_adopted" not in readme_text, (
            "README 提到 user_adopted，但 pages/06_📄_Flow_B.py 未调 update_optimization_adopted"
        )
        assert "采纳" not in _section(readme_text, "主要功能"), (
            "README '主要功能' 表的'优化建议'行不能写'点采纳'"
        )

    def test_no_liepin_crawler_command(self):
        """README '爬虫' 节不能贴 liepin 爬虫命令 —— crawler/run_crawler.py SUPPORTED_SITES 标 not yet implemented。"""
        crawler_section = _section(readme_text, "## 爬虫", "\n---\n")
        assert "--site liepin" not in crawler_section, (
            "README '爬虫' 节仍贴 liepin 命令；crawler/run_crawler.py 不支持该 site，运行会 raise ValueError"
        )

    def test_no_jobsdb_crawler_command(self):
        """README '爬虫' 节不能贴 jobsdb 爬虫命令 —— 同上未实现。"""
        crawler_section = _section(readme_text, "## 爬虫", "\n---\n")
        assert "--site jobsdb" not in crawler_section, (
            "README '爬虫' 节仍贴 jobsdb 命令；crawler/run_crawler.py 不支持该 site"
        )

    def test_liepin_jobsdb_only_in_helper_script_context(self):
        """liepin / jobsdb 字面允许出现在 '辅助脚本' 上下文（说明 M-v5 适配器待补），但禁止其他场景。"""
        crawler_section = _section(readme_text, "## 爬虫", "\n---\n")
        # 只要 crawl section 没有 liepin/jobsdb 爬虫命令，含这些字面量说明用的 is OK
        for needle in ("python crawler/run_crawler.py --site liepin",
                       "python crawler/run_crawler.py --site jobsdb"):
            assert needle not in crawler_section, (
                f"crawl section 仍含爬虫命令 {needle}"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-q", "--tb=short"])
