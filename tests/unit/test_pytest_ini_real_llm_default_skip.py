"""v1 FROZEN P0-002 闭环测试：real_llm 默认 deselect + 断言放宽。

覆盖 REVIEW.md R2 全部 3 条判定命令的静态/动态验证：

1. `pytest.ini` addopts 包含 `-m "not real_llm"`，使 `pytest` 默认跑不带 flake
2. `tests/integration/test_flow_a_real_llm_3_scenarios.py` 不再有"必须保留全部
   原数字 200/120/18"的硬断言（改为 ≥1 数字），从源头消除 flake
3. `pytest --collect-only` 在 addopts 默认配置下，real_llm 测试被 deselect
"""
from __future__ import annotations

import configparser
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PYTEST_INI = PROJECT_ROOT / "pytest.ini"
TEST_FILE = PROJECT_ROOT / "tests" / "integration" / "test_flow_a_real_llm_3_scenarios.py"


def _read_addopts() -> str:
    """读 pytest.ini 的 addopts（去行内注释/空行后 join）。"""
    cfg = configparser.ConfigParser()
    # ConfigParser 不识别 `=` 行首有空格（addopts = ...），改用 raw 读
    cfg.read(PYTEST_INI, encoding="utf-8")
    raw = cfg.get("pytest", "addopts", fallback="")
    # configparser 已经把多行合并为单字符串（以换行分隔）
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    return " ".join(lines)


def test_pytest_ini_addopts_excludes_real_llm_by_default():
    """R2-判定命令 1：addopts 默认 deselect real_llm。"""
    addopts = _read_addopts()
    assert "not real_llm" in addopts, (
        f"pytest.ini addopts 必须含 'not real_llm'（CI 默认 deselect），"
        f"实际：{addopts!r}"
    )


def test_pytest_ini_markers_declares_real_llm():
    """markers 段保留 real_llm 描述（pytest --markers 列表仍可见）。"""
    cfg = configparser.ConfigParser()
    cfg.read(PYTEST_INI, encoding="utf-8")
    markers = cfg.get("pytest", "markers", fallback="")
    assert "real_llm" in markers, f"markers 段必须声明 real_llm，实际：{markers!r}"


def test_real_llm_scenario_a_assertion_relaxed():
    """R2-判定命令 3：场景 A 断言不再是"必须保留全部 3 个数字"。

    静态扫描测试文件源码，断言不应有
    `for must_have in [...]: assert must_have in all_text` 这种全匹配循环。
    """
    src = TEST_FILE.read_text(encoding="utf-8")
    # 旧硬断言特征：for must_have in [...]  + assert must_have in all_text
    assert "for must_have in" not in src, (
        "场景 A 仍保留 `for must_have in [...]` 全匹配循环，会持续 flake；"
        "应改为 ≥1 数字保留（v1 FROZEN P0-002 决议）"
    )
    # 新断言特征：must_have = [...] + kept = [n for n in ... if n in all_text]
    assert "must_have = [" in src, (
        "场景 A 缺少 must_have = [...] 列表定义，新断言未生效"
    )
    assert "len(kept) >= 1" in src, (
        "场景 A 断言应为 len(kept) >= 1（≥1 数字），实际未找到"
    )


def test_collect_only_deselects_real_llm_tests_by_default():
    """R2-判定命令 1 动态验证：pytest --collect-only 在默认 addopts 下 0 selected。

    跑子进程 `pytest tests/integration/test_flow_a_real_llm_3_scenarios.py
    --collect-only -q`，期望输出含 "3 deselected" 且 "0 selected"。
    """
    result = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            str(TEST_FILE.relative_to(PROJECT_ROOT)),
            "--collect-only", "-q",
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    out = (result.stdout or "") + (result.stderr or "")
    # pytest --collect-only 在全部 deselect 时退出码 = 5 (no tests collected)
    # 但我们要的是断言"全部 deselect"，不是退出码
    assert "3 deselected" in out, (
        f"默认 addopts 下 3 条 real_llm 测试应被 deselect，"
        f"实际输出：\n{out}"
    )
    assert "0 selected" in out, (
        f"默认 addopts 下不应有 selected 测试，实际：\n{out}"
    )


def test_collect_only_opt_in_real_llm_selects():
    """动态验证：-m real_llm 命令行 opt-in 仍能选中 3 条 real_llm 测试。"""
    result = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            str(TEST_FILE.relative_to(PROJECT_ROOT)),
            "--collect-only", "-q", "-m", "real_llm",
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    out = (result.stdout or "") + (result.stderr or "")
    assert "3 tests collected" in out, (
        f"显式 -m real_llm 应选中 3 条测试，实际：\n{out}"
    )
