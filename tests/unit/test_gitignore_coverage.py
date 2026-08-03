# -*- coding: utf-8 -*-
"""R9 P1-013 回归：debug 工件已入 .gitignore + 历史残留不再 untracked。

两层防护：
1. 历史遗物：R9 之前 untracked 的 debug / 评估产物现在 ``git status`` 显示为
   ``!!`` 前缀（ignored），不会被误 commit
2. 未来同类：未来再产生同类工件 → ``git check-ignore`` 立即识别为 ignored
   （不依赖真实创建该文件，不污染 repo）

中文 / 空格的路径走 ``git -c core.quotepath=false``，避免 Win 上输出
octal 转义字符串导致字符串比较失败。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

_GIT_STATUS_ARGS = [
    "git", "-c", "core.quotepath=false",
    "status", "--ignored", "--porcelain",
]


def _git_status_ignored_files() -> list[str]:
    out = subprocess.run(
        _GIT_STATUS_ARGS,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    paths: list[str] = []
    for line in out.splitlines():
        line = line.rstrip()
        if not line:
            continue
        if line.startswith("!! "):
            p = line[3:].strip()
        elif line.startswith("!!"):
            p = line[2:].strip()
        else:
            continue
        # git 在路径含空格 / 中文时会用 `"..."` 包名；normalize
        if len(p) >= 2 and p.startswith('"') and p.endswith('"'):
            p = p[1:-1]
        paths.append(p)
    return paths


def _git_status_untracked_files() -> list[str]:
    out = subprocess.run(
        [
            "git", "-c", "core.quotepath=false",
            "status", "--porcelain",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    paths: list[str] = []
    for line in out.splitlines():
        line = line.rstrip()
        if line.startswith("?? "):
            paths.append(line[3:].strip())
    return paths


def _git_check_ignore(path: str) -> bool:
    """``git check-ignore`` 判断路径是否被 ignore（不创建文件）。"""
    result = subprocess.run(
        ["git", "-c", "core.quotepath=false", "check-ignore", path],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    # returncode 0 = ignored; 1 = not ignored; 128 = error
    return result.returncode == 0


# ---------------------------------------------------------------------------
# 1. R9 历史遗物：曾经 untracked 的 debug 产物现在 ``git status`` 报 ignored
# ---------------------------------------------------------------------------

class TestHistoricalDebugArtifactsIgnored:
    """确认每条 R9 列出的"历史 untracked debug 工件"现在都被忽略。"""

    @pytest.mark.parametrize(
        "filename",
        [
            # 评测 / miss analysis / DB 备份
            "data/eval_baseline_20260802T211059Z.json",
            "data/miss_analysis_20260725T164938Z.md",
            "data/post_backfill_eval_20260726T080343Z.md",
            "data/jobhunter_v2.db.bak_1782226358",
            "data/jobhunter_v2.db.bak_before_classify",
            # 缓存 / 探针
            "data/rag_progress.json",
            "data/sqlite_vec_validation.json",
            "data/liepin_homepage_text.txt",
            "data/poll_streamlit.ps1",
            # 文档/调试脚本
            "coverage.xml",
            "AI Agent产品经理_简历.md",
            "docs/portfolio.md",
        ],
    )
    def test_historical_artifact_is_ignored(self, filename: str):
        """每条列出的文件必须是 ``git status --ignored`` 中的 ignored 项。"""
        ignored = _git_status_ignored_files()
        assert filename in ignored, (
            f"{filename} 未被 .gitignore 覆盖；请检查 .gitignore 末尾 "
            f"的 'R9 P1-013 治理' 块。"
        )

    def test_no_historical_artifacts_remain_untracked(self):
        """曾经 untracked 的 R9 列出的文件都不应再出现 ``??`` untracked 列表。

        强语义：一旦 .gitignore 生效，原本要 commit 的那批 debug 工件就
        应该自动从 untracked 列表消失。"""
        untracked = _git_status_untracked_files()
        for filename in [
            "data/eval_baseline_20260802T211059Z.json",
            "data/miss_analysis_20260725T164938Z.md",
            "data/jobhunter_v2.db.bak_1782226358",
            "data/rag_progress.json",
            "data/sqlite_vec_validation.json",
            "data/liepin_homepage_text.txt",
            "docs/portfolio.md",
        ]:
            assert filename not in untracked, (
                f"{filename} 应已被 ignore，但仍出现在 untracked — "
                f".gitignore 模式未生效"
            )


# ---------------------------------------------------------------------------
# 2. 未来同类：新建符合模式的文件 → ``git check-ignore`` 立即识别为 ignored
# ---------------------------------------------------------------------------

class TestNewArtifactsImmediatelyIgnored:
    """R9 P1-013 的可扩展性：未来再产生同类工件 → 自动被忽略。"""

    @pytest.mark.parametrize(
        "filename",
        [
            "data/eval_baseline_test_xxx.json",
            "data/miss_analysis_test_yyy.md",
            "data/post_backfill_eval_test_zzz.md",
            "data/jobhunter_v2.db.bak_test_12345",
            "data/rag_progress_v2_test.json",
            "data/sqlite_vec_test_v2.json",
        ],
    )
    def test_pattern_catches_future_file(self, filename: str):
        """``git check-ignore``（不创建文件）应识别这些未来同类工件。"""
        is_ignored = _git_check_ignore(filename)
        assert is_ignored, (
            f"{filename} 未被 .gitignore 覆盖；R9 P1-013 治理模式漏覆盖，"
            f"未来同类文件将作为 untracked 泄漏到 git status。"
        )
