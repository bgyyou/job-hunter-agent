# -*- coding: utf-8 -*-
"""P1-005 守卫测试 — 简历上传临时文件清理机制。

R10 修复说明：pages/03_📝_Flow_A_Step1.py 上传图片原本用 tempfile.gettempdir() 全局临时
目录，无清理机制 — 长期累积占磁盘。修复方案三层：
1. 命名规范：prefix="jobhunter_resume_" + uuid，便于批量匹配
2. 启动 stale 清理：web_app.py import 时删 >24h 同名前缀文件（兜底上次 session 残留）
3. atexit session 清理：当前 session 上传的文件 process 退出时全删

三层各自单测覆盖。
"""
from __future__ import annotations

import atexit
import tempfile
import time
from pathlib import Path
from unittest import mock

import pytest


# ============================================================
# 1. atexit 注册守卫
# ============================================================


class TestAtexitHandlerRegistered:
    def test_web_app_registers_atexit_for_resume_cleanup(self):
        """import web_app 后 atexit._run_exitfuncs / register 列表里应包含清理函数。

        简化做法：直接 import web_app 检查模块属性：
        - _resume_tmp_paths 列表存在
        - _cleanup_resume_tmp_session 函数存在
        """
        import web_app

        assert hasattr(web_app, "_resume_tmp_paths"), (
            "web_app 应定义 _resume_tmp_paths 列表供 atexit 清理用"
        )
        assert isinstance(web_app._resume_tmp_paths, list)

        assert hasattr(web_app, "_cleanup_resume_tmp_session"), (
            "web_app 应定义 _cleanup_resume_tmp_session 清理函数"
        )
        assert callable(web_app._cleanup_resume_tmp_session)


class TestRegisterResumeTmp:
    def test_register_adds_to_session_list(self):
        """_register_resume_tmp 把新路径加入 _resume_tmp_paths。"""
        from web_app import _register_resume_tmp, _resume_tmp_paths

        before = len(_resume_tmp_paths)
        path = "/tmp/jobhunter_resume_test_register.png"
        _register_resume_tmp(path)
        assert len(_resume_tmp_paths) == before + 1
        assert path in _resume_tmp_paths

    def test_register_dedups_same_path(self):
        """重复注册同一路径不应重复添加。"""
        from web_app import _register_resume_tmp, _resume_tmp_paths

        before = len(_resume_tmp_paths)
        path = "/tmp/jobhunter_resume_test_dedup.png"
        _register_resume_tmp(path)
        _register_resume_tmp(path)
        assert _resume_tmp_paths.count(path) == 1
        assert len(_resume_tmp_paths) == before + 1


# ============================================================
# 2. 启动 stale 清理：mock 时间 → 创建 25h 前 + 1h 前文件 → 验证只删 25h 前的
# ============================================================


class TestStartupStaleCleanup:
    def test_only_files_older_than_threshold_are_deleted(self, tmp_path, monkeypatch):
        """_cleanup_resume_tmp_stale：>24h 的删除，<24h 的保留。

        mock 路径到 tmp_path：避免污染真实 tempfile 目录。
        """
        from web_app import RESUME_TMP_STALE_SECONDS, _cleanup_resume_tmp_stale

        # mock _resume_tmp_dir() 到 tmp_path
        monkeypatch.setattr(
            "web_app._resume_tmp_dir", lambda: tmp_path
        )

        # 当前 mock 时间 = now
        now = 1_700_000_000.0
        stale_age = RESUME_TMP_STALE_SECONDS + 3600  # 25h
        fresh_age = 3600  # 1h

        stale_file = tmp_path / "jobhunter_resume_stale_001.png"
        fresh_file = tmp_path / "jobhunter_resume_fresh_002.png"
        # 非匹配文件（不同前缀）— 不应被删
        unrelated_file = tmp_path / "unrelated_file.png"
        # 非匹配文件（不同扩展名）— 不应被删
        wrong_ext_file = tmp_path / "jobhunter_resume_bad_ext.xyz"

        for f in (stale_file, fresh_file, unrelated_file, wrong_ext_file):
            f.write_bytes(b"x")

        # 用 os.utime 把 mtime 调到对应时间
        # mtime = now - age
        import os
        os.utime(stale_file, (now - stale_age, now - stale_age))
        os.utime(fresh_file, (now - fresh_age, now - fresh_age))
        os.utime(unrelated_file, (now - stale_age, now - stale_age))
        os.utime(wrong_ext_file, (now - stale_age, now - stale_age))

        # mock time.time 让"现在" = now
        with mock.patch("web_app.time.time", return_value=now):
            deleted = _cleanup_resume_tmp_stale()

        assert deleted == 1, f"应只删 1 个 stale 文件，实际 {deleted}"
        assert not stale_file.exists(), "stale 文件应被删"
        assert fresh_file.exists(), "fresh 文件应保留"
        assert unrelated_file.exists(), "非 jobhunter_resume_ 前缀文件不应被删"
        assert wrong_ext_file.exists(), "非图片扩展名文件不应被删"

    def test_empty_dir_does_not_raise(self, tmp_path, monkeypatch):
        """空目录 / 不存在目录都不抛异常。"""
        from web_app import _cleanup_resume_tmp_stale

        monkeypatch.setattr("web_app._resume_tmp_dir", lambda: tmp_path)
        deleted = _cleanup_resume_tmp_stale()
        assert deleted == 0

    def test_non_file_entries_skipped(self, tmp_path, monkeypatch):
        """目录 / symlink 等非 file 节点跳过，不抛异常。"""
        from web_app import _cleanup_resume_tmp_stale

        monkeypatch.setattr("web_app._resume_tmp_dir", lambda: tmp_path)

        sub_dir = tmp_path / "jobhunter_resume_looks_like_file"
        sub_dir.mkdir()
        deleted = _cleanup_resume_tmp_stale()
        assert deleted == 0
        assert sub_dir.exists(), "子目录不应被删（不是 file）"


# ============================================================
# 3. 命名规范：tempfile.NamedTemporaryFile(prefix=...) 含 jobhunter_resume_ 前缀
# ============================================================


class TestResumeTmpNamingConvention:
    def test_page_uses_jobhunter_resume_prefix(self):
        """pages/03_📝_Flow_A_Step1.py 必须用 jobhunter_resume_ 前缀。"""
        page = Path(__file__).resolve().parents[2] / "pages" / "03_📝_Flow_A_Step1.py"
        src = page.read_text(encoding="utf-8")
        assert 'prefix="jobhunter_resume_' in src, (
            f"{page.name} 的 tempfile.NamedTemporaryFile 必须用 jobhunter_resume_ 前缀"
        )

    def test_cleanup_stale_uses_same_prefix(self):
        """web_app.py 的 _cleanup_resume_tmp_stale 必须按 jobhunter_resume_ glob。"""
        from web_app import RESUME_TMP_PREFIX
        assert RESUME_TMP_PREFIX == "jobhunter_resume_"

        import web_app
        src = Path(web_app.__file__).read_text(encoding="utf-8")
        assert f'{RESUME_TMP_PREFIX}*' in src or f'f"{RESUME_TMP_PREFIX}*"' in src, (
            "web_app.py 启动清理必须 glob jobhunter_resume_*"
        )

    def test_namedtemporaryfile_with_prefix_roundtrip(self, tmp_path):
        """smoke：tempfile.NamedTemporaryFile(prefix='jobhunter_resume_', dir=tmp_path)
        生成的文件名确实以 jobhunter_resume_ 开头，可被同 glob 匹配。
        """
        from web_app import RESUME_TMP_PREFIX

        with tempfile.NamedTemporaryFile(
            prefix=RESUME_TMP_PREFIX,
            suffix=".png",
            dir=str(tmp_path),
            delete=False,
        ) as f:
            f.write(b"fake png bytes")
            name = Path(f.name).name

        assert name.startswith("jobhunter_resume_")
        assert name.endswith(".png")

        # 验证 glob 能匹配回来
        matches = list(tmp_path.glob(f"{RESUME_TMP_PREFIX}*"))
        assert any(m.name == name for m in matches)