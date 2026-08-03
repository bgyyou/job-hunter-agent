# -*- coding: utf-8 -*-
"""P1-004 守卫测试 — setup_wizard 不调 set_page_config。

R10 修复说明：setup_wizard.py:70 原 st.set_page_config(...) 与 web_app.py:49-54 冲突，
新 streamlit 版本会抛 StreamlitAPIException。修复后由 web_app.py 统一控制。
两层防护：
1. AST 静态扫描 — setup_wizard.py 源文件不出现 "set_page_config" 字面量
2. import smoke — import setup_wizard 不抛 StreamlitAPIException
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SETUP_WIZARD_PATH = REPO_ROOT / "setup_wizard.py"


class TestSetupWizardNoPageConfig:
    def test_source_file_has_no_set_page_config_literal(self):
        """AST 扫描 setup_wizard.py：源码字面量无 set_page_config。

        用 AST 而不是 grep：避开注释 / docstring 误命中。
        只检查真实代码节点（Attribute/Name 调用 + ast.literal_eval 字符串）。
        """
        src = SETUP_WIZARD_PATH.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(SETUP_WIZARD_PATH))

        violations = []
        for node in ast.walk(tree):
            # 检查函数调用：func.attr == "set_page_config"
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "set_page_config":
                    violations.append(
                        f"line {node.lineno}: 调用 {ast.dump(func)}"
                    )
            # 检查 ast.literal_eval 出现的字符串（防把 set_page_config 当常量塞进代码）
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if "set_page_config" in node.value:
                    violations.append(
                        f"line {node.lineno}: 字符串字面量含 set_page_config: {node.value!r}"
                    )

        assert not violations, (
            "P1-004 守卫失败 — setup_wizard.py 不应再出现 set_page_config:\n  "
            + "\n  ".join(violations)
        )

    def test_import_setup_wizard_does_not_raise_streamlit_api_exception(self):
        """import setup_wizard 不抛 StreamlitAPIException。

        set_page_config 在新 streamlit 多 page 模式下会抛该异常。
        我们不在 streamlit 实际跑 setup_wizard，只 import — 但 import 路径仍可能触发。
        """
        # import 时若 setup_wizard 在模块级调了 set_page_config()，streamlit 会抛
        # 这里 try/except 仅拦截我们关心的异常，其他 Exception 让其正常冒泡
        try:
            import setup_wizard  # noqa: F401
        except Exception as exc:
            # StreamlitAPIException 在不同版本类名可能变，这里用模块名匹配
            cls_name = type(exc).__name__
            if "StreamlitAPIException" in cls_name or "set_page_config" in str(exc).lower():
                pytest.fail(
                    f"P1-004 回归 — import setup_wizard 抛 {cls_name}: {exc}"
                )
            raise