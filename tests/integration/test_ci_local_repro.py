"""CI dependency and pytest-asyncio local reproduction guards."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_ci_installs_scipy():
    workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    assert '"scipy>=' in workflow


def test_pytest_configures_asyncio_mode():
    pytest_ini = (ROOT / "pytest.ini").read_text(encoding="utf-8")
    assert "asyncio_mode = auto" in pytest_ini


@pytest.mark.asyncio
async def test_asyncio_event_loop_smoke():
    await asyncio.sleep(0)
    assert asyncio.get_running_loop().is_running()
