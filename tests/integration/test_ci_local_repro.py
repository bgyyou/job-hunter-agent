"""CI dependency and pytest-asyncio local reproduction guards."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]

# M-v4-2 P1-016 闭环：CI 最小依赖必须覆盖以下全部，否则 R7 / 渲染 / 解析测试会因
# ModuleNotFoundError 全军覆没。scipy 是 R7 vec0 检索需要；jinja2 / python-docx /
# beautifulsoup4 / lxml 是 document_generator.py 真实渲染路径需要的。
CI_REQUIRED_DEPS = (
    "scipy>=",
    "jinja2>=",
    "python-docx>=",
    "beautifulsoup4>=",
    "lxml>=",
)


def test_ci_installs_required_deps():
    workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    missing = [token for token in CI_REQUIRED_DEPS if f'"{token}' not in workflow]
    assert not missing, (
        f"CI workflow 缺装以下依赖：{missing}。"
        "在 .github/workflows/test.yml 的 'Install minimal test deps' 步骤里补齐，"
        "否则 GitHub Actions 上的 pytest 会因 ModuleNotFoundError 全红。"
    )


def test_pytest_configures_asyncio_mode():
    pytest_ini = (ROOT / "pytest.ini").read_text(encoding="utf-8")
    assert "asyncio_mode = auto" in pytest_ini


def test_unit_tests_do_not_use_get_event_loop():
    """pytest-asyncio 1.x 下 `asyncio.get_event_loop()` 在主线程里没有当前 loop，
    会抛 RuntimeError。unit 测试要么用 `asyncio.new_event_loop()`（首选），
    要么改成 async + @pytest.mark.asyncio。"""
    import ast

    tests_dir = ROOT / "tests"
    offenders: list[str] = []
    for py_file in tests_dir.rglob("*.py"):
        if not py_file.is_file():
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            # 形如 asyncio.get_event_loop().run_until_complete(...)
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "run_until_complete"
                and isinstance(func.value, ast.Call)
                and isinstance(func.value.func, ast.Attribute)
                and func.value.func.attr == "get_event_loop"
            ):
                offenders.append(str(py_file.relative_to(ROOT)))
                break
    assert not offenders, (
        "以下 unit 测试仍使用已弃用的 asyncio.get_event_loop() 同步入口：\n"
        + "\n".join(offenders)
        + "\n→ 改用 asyncio.new_event_loop() + try/finally loop.close() 模式，"
        "参考 tests/unit/test_resume_flow_a_streaming.py:72-77。"
    )


@pytest.mark.asyncio
async def test_asyncio_event_loop_smoke():
    await asyncio.sleep(0)
    assert asyncio.get_running_loop().is_running()
