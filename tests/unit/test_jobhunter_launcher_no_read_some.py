"""R7 守卫：scripts/jobhunter_launcher.py 不得包含 `_read_some` 死函数。

背景：R6 (`77f5032`) 删除 P1-007 后只保留后台线程 `_drain` 作为唯一输出读取路径。
后续若有人复活 `_read_some`（立即 return "" 的死函数），这两个守卫立刻失败。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

LAUNCHER_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "jobhunter_launcher.py"
)
PROJECT_ROOT = LAUNCHER_PATH.resolve().parents[2]

# 不递归扫描的目录（避免 Windows 跨盘拒绝访问兄弟项目 venv + 跳过无意义缓存）
_SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", "build", "dist"}


def _iter_py_files(root: Path):
    """yield Path(root) 下的所有 .py 文件；跳过常见虚拟/缓存/构建目录，避免跨项目触发 WinError 1920。"""
    for entry in root.iterdir():
        if entry.is_dir():
            if entry.name in _SKIP_DIRS:
                continue
            yield from _iter_py_files(entry)
        elif entry.is_file() and entry.suffix == ".py":
            yield entry


def test_launcher_defines_no_read_some():
    """AST 扫描 launcher.py，def _read_some 出现次数必须等于 0。"""
    src = LAUNCHER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(src)
    matches = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_read_some"
    ]
    assert not matches, (
        f"_read_some 在 {LAUNCHER_PATH.name} 内重新出现（{len(matches)} 次），"
        "P1-007 修复要求彻底删除（threading _drain 已替代）。"
    )


def test_no_read_some_anywhere_in_repo():
    """全仓 grep `_read_some`，必须 0 命中（除本测试文件）。"""
    pattern = re.compile(r"\b_read_some\b")
    offenders: list[Path] = []
    for py_file in _iter_py_files(PROJECT_ROOT):
        # 跳过守卫自身（标识符 _read_some 出现在测试逻辑里）
        if py_file.name == "test_jobhunter_launcher_no_read_some.py":
            continue
        try:
            content = py_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if pattern.search(content):
            offenders.append(py_file.relative_to(PROJECT_ROOT))
    assert not offenders, (
        "_read_some 出现在以下文件中（P1-007 修复要求全仓 0 命中）：\n"
        + "\n".join(f"  - {p}" for p in offenders)
    )
