"""R7 守卫：scripts/jobhunter_launcher.py 内 `find_python_for_streamlit` 必须只定义一次。

背景：R6 (`6c146f6`) 删除 P1-006 重复定义后保留唯一实现。后续若有人 copy-paste 制造第二份，
这两个守卫立刻失败。
"""
from __future__ import annotations

import ast
from pathlib import Path

LAUNCHER_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "jobhunter_launcher.py"
)


def _load_func_defs() -> list[ast.FunctionDef]:
    src = LAUNCHER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(src)
    return [
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "find_python_for_streamlit"
    ]


def test_find_python_for_streamlit_defined_once():
    """AST 扫描 launcher.py，def find_python_for_streamlit 出现次数必须等于 1。"""
    defs = _load_func_defs()
    assert len(defs) == 1, (
        f"find_python_for_streamlit 在 {LAUNCHER_PATH.name} 内出现 {len(defs)} 次，"
        "P1-006 修复要求只保留唯一实现。"
    )


def test_find_python_for_streamlit_first_definition_has_real_body():
    """第一个定义的函数体必须非空 + 含实际逻辑（不是纯 pass 或 docstring-only）。"""
    defs = _load_func_defs()
    assert defs, "应当存在至少一个 find_python_for_streamlit 定义"
    first = defs[0]
    body = first.body
    assert body, "函数体为空"
    # 至少有一个非 Expr(stub) 的语句 — Pass / docstring 都不算"实际逻辑"
    has_real_stmt = any(
        not (isinstance(stmt, ast.Pass) or
             (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)))
        for stmt in body
    )
    assert has_real_stmt, "find_python_for_streamlit 退化到仅 pass/docstring，无实际逻辑"
