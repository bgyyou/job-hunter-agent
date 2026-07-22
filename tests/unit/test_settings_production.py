# -*- coding: utf-8 -*-
"""v4 T0.4：settings production 分支单测。"""
from __future__ import annotations

from config.settings import Settings


class TestProductionFlag:
    def test_default_is_development(self, monkeypatch):
        monkeypatch.delenv("ENV", raising=False)
        assert Settings().is_production is False

    def test_production_env(self, monkeypatch):
        monkeypatch.setenv("ENV", "production")
        assert Settings().is_production is True

    def test_case_and_whitespace_tolerant(self, monkeypatch):
        monkeypatch.setenv("ENV", "  Production ")
        assert Settings().is_production is True

    def test_other_values_not_production(self, monkeypatch):
        monkeypatch.setenv("ENV", "staging")
        assert Settings().is_production is False

    def test_production_logging_uses_json(self, monkeypatch, tmp_path):
        """production 下 setup_logging 走 serialize（JSON），且不报错。"""
        monkeypatch.setenv("ENV", "production")
        monkeypatch.setenv("LOG_DIR", str(tmp_path))
        s = Settings()
        s.setup_logging()
        from loguru import logger

        logger.info("v4-settings-test")
        logger.complete()
        log_file = tmp_path / s.log_file
        assert log_file.exists()
        line = log_file.read_text(encoding="utf-8").strip().splitlines()[-1]
        assert line.startswith("{"), "production 日志应为 JSON"
        assert "v4-settings-test" in line
