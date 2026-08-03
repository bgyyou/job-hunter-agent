"""Regression guards for the ops metrics SQL extraction API."""
from __future__ import annotations

import inspect
from pathlib import Path

from services import ops_metrics


ROOT = Path(__file__).resolve().parents[2]


def test_generic_json_extract_is_not_exposed():
    assert not any(
        name == "_json_extract_sql"
        for name, member in inspect.getmembers(ops_metrics, inspect.isfunction)
    )


def test_ops_dashboard_has_no_generic_json_extract_call():
    source = (ROOT / "pages" / "99_📊_Ops.py").read_text(encoding="utf-8")
    assert "_json_extract_sql(" not in source
