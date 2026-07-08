# -*- coding: utf-8 -*-
"""JobHunter launcher 单测：is_server_ready + get_project_root + parse_streamlit_url。

避免真跑 streamlit 子进程。scripts/ 不是包，用 importlib 直接按文件加载。"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


ROOT = Path(__file__).resolve().parents[2]  # tests/unit → tests → project root
_LAUNCHER_PATH = ROOT / "scripts" / "jobhunter_launcher.py"

_spec = importlib.util.spec_from_file_location("jobhunter_launcher", _LAUNCHER_PATH)
launcher = importlib.util.module_from_spec(_spec)
sys.modules["jobhunter_launcher"] = launcher
_spec.loader.exec_module(launcher)


def test_get_project_root_unfrozen():
    """未 frozen 时 web_app 同目录即项目根。"""
    web_app = Path(__file__).resolve().parents[2] / "web_app.py"
    root = launcher.get_project_root(web_app)
    assert root == web_app.parent
    assert (root / "scripts" / "jobhunter_launcher.py").exists()


def test_get_project_root_frozen():
    """get_project_root 只是简单返回 web_app 的 parent，与 frozen 状态无关。
    用正斜杠 'C:/dist' 是为了让该测试在 Linux / Windows 上行为一致：
    Path 在 Windows 上同时接受正反斜杠，反斜杠形式在 Linux 上会被当成单个文件名。
    """
    web_app = Path("C:/dist/web_app.py")
    root = launcher.get_project_root(web_app)
    assert str(root).replace("\\", "/") == "C:/dist"


def test_parse_streamlit_url_extracts_port():
    """从 streamlit 启动 banner 里抓端口。"""
    out = "  You can now view your Streamlit app in your browser.\n  Network URL: http://192.168.1.5:8501\n"
    assert launcher.parse_streamlit_url(out, 8501) == 8501


def test_parse_streamlit_url_falls_back_to_default():
    """没有匹配端口就用默认。"""
    assert launcher.parse_streamlit_url("no url here", 8765) == 8765


def test_is_server_ready_returns_false_on_connection_refused():
    """端口未开 / 连不上 → False。"""
    # 1 一定没用就返回 False（connection refused）
    assert launcher.is_server_ready("http://localhost:1", timeout=0.3) is False


def test_is_server_ready_returns_true_when_4xx():
    """streamlit 启动中可能返 503，4xx 仍算"服务在"。"""
    fake_resp = MagicMock()
    fake_resp.status = 503

    with patch("urllib.request.urlopen") as mock_urlopen:
        ctx = MagicMock()
        ctx.__enter__.return_value = fake_resp
        ctx.__exit__.return_value = False
        mock_urlopen.return_value = ctx
        assert launcher.is_server_ready("http://localhost:8501") is True
    mock_urlopen.assert_called_once()


def test_is_server_ready_returns_false_on_timeout():
    """超时 → False。"""
    import socket

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = socket.timeout()
        assert launcher.is_server_ready("http://localhost:8501") is False
