"""perf_measure_pages.py 集成测试 — 验证 R9-P1 埋点脚本可加载、可跑、输出符合契约。

历史：R13b-prep（2026-08-04）落地 R9-P1 测量方式入口。脚本本身通过
subprocess 跑（owner 本机执行），单测这里覆盖两条关键不变量：
1. import 干净（无 ImportError、无未捕获异常）。
2. main() 跑通后会输出 5 个页面名 + 平均耗时行。
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
PERF_MODULE = "scripts.perf_measure_pages"

EXPECTED_PAGE_KEYS = (
    "Flow_A_Step1",
    "Flow_A_Step2",
    "Flow_B",
    "JD_Library",
    "Application_History",
)


@pytest.fixture
def perf_module():
    """每次清缓存重 import，避免上次 subprocess 把 sys.modules 污染。"""
    sys.modules.pop(PERF_MODULE, None)
    return importlib.import_module(PERF_MODULE)


def test_script_module_imports_cleanly(perf_module) -> None:
    """脚本 import 不报 ImportError；暴露 main + measure_page + PAGES。"""
    assert callable(getattr(perf_module, "main", None))
    assert callable(getattr(perf_module, "measure_page", None))
    pages = getattr(perf_module, "PAGES", None)
    assert isinstance(pages, (list, tuple))
    assert len(pages) == 5, f"expected 5 pages per R9-P1, got {len(pages)}"


def test_main_reports_all_pages_and_average(monkeypatch, capsys, perf_module) -> None:
    """main() mock 模式下应输出 5 行 + 1 行平均，rc=0。"""
    monkeypatch.setattr(perf_module, "measure_page", lambda p, timeout: 0.5)
    monkeypatch.setattr(sys, "argv", ["perf_measure_pages.py"])

    rc = perf_module.main()
    out = capsys.readouterr().out

    assert rc == 0, f"main() returned {rc}; output:\n{out}"
    for name in EXPECTED_PAGE_KEYS:
        assert name in out, f"{name} not in output:\n{out}"
    assert "平均" in out, f"average line missing:\n{out}"