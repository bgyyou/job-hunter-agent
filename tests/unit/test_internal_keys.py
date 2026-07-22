# -*- coding: utf-8 -*-
"""config.internal_keys — v2.1 P2-1 阶段一"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """每个 case 前后确保 LLM_* 环境变量干净，否则会污染其他测试。"""
    for k in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "JOBHUNTER_INTERNAL_KEYS"):
        monkeypatch.delenv(k, raising=False)
    yield
    for k in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "JOBHUNTER_INTERNAL_KEYS"):
        monkeypatch.delenv(k, raising=False)


@pytest.fixture
def fake_internal_keys(tmp_path: Path) -> Path:
    p = tmp_path / "internal_keys.json"
    p.write_text(
        json.dumps(
            {
                "api_key": "test-key-fake",
                "base_url": "https://example.com/v1",
                "model": "fake-model-x",
            }
        ),
        encoding="utf-8",
    )
    return p


def test_apply_writes_when_env_empty(monkeypatch, fake_internal_keys):
    monkeypatch.setenv("JOBHUNTER_INTERNAL_KEYS", str(fake_internal_keys))
    from config import internal_keys
    applied, src = internal_keys.apply_internal_keys()
    assert applied is True
    assert src == fake_internal_keys
    assert os.environ["LLM_API_KEY"] == "test-key-fake"
    assert os.environ["LLM_BASE_URL"] == "https://example.com/v1"
    assert os.environ["LLM_MODEL"] == "fake-model-x"


def test_apply_skips_when_env_already_set(monkeypatch, fake_internal_keys):
    monkeypatch.setenv("JOBHUNTER_INTERNAL_KEYS", str(fake_internal_keys))
    monkeypatch.setenv("LLM_API_KEY", "key-from-env")  # 用户 .env 显式配过
    from config import internal_keys
    applied, src = internal_keys.apply_internal_keys()
    assert applied is False
    assert src is None
    # env 没被覆盖 — 用户优先
    assert os.environ["LLM_API_KEY"] == "key-from-env"


def test_apply_force_overrides(monkeypatch, fake_internal_keys):
    """launcher 用 force=True 覆盖（虽然实际不会触发，安全网）。"""
    monkeypatch.setenv("JOBHUNTER_INTERNAL_KEYS", str(fake_internal_keys))
    monkeypatch.setenv("LLM_API_KEY", "old-test-key")
    from config import internal_keys
    applied, src = internal_keys.apply_internal_keys(force=True)
    assert applied is True
    assert os.environ["LLM_API_KEY"] == "test-key-fake"


def test_missing_file_returns_false(monkeypatch, tmp_path):
    """env 指向不存在的文件 → 不抛、返回 False。"""
    monkeypatch.setenv(
        "JOBHUNTER_INTERNAL_KEYS", str(tmp_path / "nope.json")
    )
    from config import internal_keys
    applied, src = internal_keys.apply_internal_keys()
    assert applied is False
    assert src is None
    assert "LLM_API_KEY" not in os.environ


def test_invalid_json_tolerated(monkeypatch, tmp_path):
    """JSON 损坏不抛，返回 False。"""
    bad = tmp_path / "bad.json"
    bad.write_text("not json {", encoding="utf-8")
    monkeypatch.setenv("JOBHUNTER_INTERNAL_KEYS", str(bad))
    from config import internal_keys
    applied, src = internal_keys.apply_internal_keys()
    assert applied is False
    assert src is None


def test_empty_api_key_ignored(monkeypatch, tmp_path):
    """api_key 为空字符串视为未配置。"""
    p = tmp_path / "empty.json"
    p.write_text(json.dumps({"api_key": "", "base_url": "x", "model": "y"}), encoding="utf-8")
    monkeypatch.setenv("JOBHUNTER_INTERNAL_KEYS", str(p))
    from config import internal_keys
    applied, src = internal_keys.apply_internal_keys()
    assert applied is False
    assert "LLM_API_KEY" not in os.environ


def test_is_internal_beta_active_detects_active_file(monkeypatch, fake_internal_keys):
    monkeypatch.setenv("JOBHUNTER_INTERNAL_KEYS", str(fake_internal_keys))
    from config import internal_keys
    assert internal_keys.is_internal_beta_active() is True


def test_is_internal_beta_active_no_file(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBHUNTER_INTERNAL_KEYS", str(tmp_path / "nope.json"))
    from config import internal_keys
    assert internal_keys.is_internal_beta_active() is False


def test_defaults_when_partial_json(monkeypatch, tmp_path):
    """只填 api_key 的最小配置也能用，base_url/model 有默认值。"""
    p = tmp_path / "min.json"
    p.write_text(json.dumps({"api_key": "minimal-test-key"}), encoding="utf-8")
    monkeypatch.setenv("JOBHUNTER_INTERNAL_KEYS", str(p))
    from config import internal_keys
    applied, _ = internal_keys.apply_internal_keys()
    assert applied is True
    assert os.environ["LLM_API_KEY"] == "minimal-test-key"
    # 默认值兜底
    assert "LLM_BASE_URL" in os.environ
    assert "LLM_MODEL" in os.environ


class TestProductionGuard:
    """v4 T1.6：ENV=production 时 internal beta 强制禁用（防明文 key 上公网）。"""

    def test_production_disables_internal_beta(self, monkeypatch, fake_internal_keys):
        from config.internal_keys import is_internal_beta_active

        monkeypatch.setenv("JOBHUNTER_INTERNAL_KEYS", str(fake_internal_keys))
        monkeypatch.setenv("ENV", "production")
        assert is_internal_beta_active() is False

    def test_non_production_still_active(self, monkeypatch, fake_internal_keys):
        from config.internal_keys import is_internal_beta_active

        monkeypatch.setenv("JOBHUNTER_INTERNAL_KEYS", str(fake_internal_keys))
        monkeypatch.setenv("ENV", "development")
        assert is_internal_beta_active() is True
