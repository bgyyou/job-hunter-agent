# -*- coding: utf-8 -*-
"""R9 P1-013 + R11 P1-017 回归：debug 工件已入 .gitignore，CI 干净 runner 上也成立。

两层防护（用 ``git check-ignore -v <path>`` 直接探测 .gitignore 规则）：

1. **历史遗物**：R9 之前 untracked 的 debug / 评估产物现在被 .gitignore 规则
   覆盖。``git check-ignore`` 对路径字面量做规则匹配，**不读文件系统**——
   文件是否物理存在无关，CI 干净 runner（没把本地调试产物 copy 过去）也能通过。
2. **未来同类**：未来再产生同类工件 → ``git check-ignore`` 立即识别为 ignored
   （不创建文件、不污染 repo）。

**根因（commit <R11 TBD> 修复）**：旧测试用 ``git status --ignored --porcelain``
解析 ``!!`` 前缀 —— ``git status --ignored`` 只对**实际存在**的路径报告
ignored，CI 干净 runner 上 12 条全 fail。改成 ``git check-ignore`` 后，
规则匹配与文件系统解耦，本地 / CI 行为一致。

中文 / 空格的路径走 ``git -c core.quotepath=false``，避免 Win 上输出
octal 转义字符串导致字符串比较失败。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _git_check_ignore(path: str) -> tuple[int, str, str]:
    """调 ``git check-ignore -v <path>``，返 (returncode, stdout, stderr)。

    - returncode 0 = 被忽略；stdout 形如 ``.gitignore:123:<rule>\\t<path>``
    - returncode 1 = 未被忽略
    - returncode 128 = git 错误（路径格式不合法等）
    """
    result = subprocess.run(
        ["git", "-c", "core.quotepath=false", "check-ignore", "-v", path],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.returncode, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# 1. R9 P1-013 历史遗物：曾经 untracked 的 debug 产物现在被 .gitignore 规则覆盖
#    （不依赖文件物理存在 — git check-ignore 只对路径字面量做规则匹配）
# ---------------------------------------------------------------------------

class TestHistoricalDebugArtifactsIgnored:
    """确认每条 R9 列出的"历史 untracked debug 工件"路径被 .gitignore 规则覆盖。

    与 R9 旧版区别：旧版调 ``git status --ignored``，要求文件物理存在；
    本版调 ``git check-ignore -v <path>``，**只对路径字面量做规则匹配**。
    CI 干净 runner（无 ``data/eval_baseline_*.json`` 等本地调试产物）也能过。
    """

    @pytest.mark.parametrize(
        "artifact_path",
        [
            # 评测 / miss analysis / DB 备份（exercise 通配规则）
            "data/eval_baseline_20260724T011622Z.json",
            "data/miss_analysis_20260725T164938Z.md",
            "data/post_backfill_eval_20260726T080343Z.md",
            "data/jobhunter_v2.db.bak_1782226358",
            # 缓存 / 探针
            "data/rag_progress.json",
            "data/sqlite_vec_validation.json",
            "data/liepin_homepage_text.txt",
            "data/portfolio.md",
            "data/poll_streamlit.ps1",
            # 顶层产物
            "coverage.xml",
            # 中文 / docs/portfolio
            "AI Agent产品经理_简历.md",
            "docs/portfolio.md",
        ],
    )
    def test_gitignore_rule_covers_historical_artifact(self, artifact_path: str):
        """``git check-ignore`` 直接探测规则覆盖，不依赖文件物理存在。"""
        rc, stdout, stderr = _git_check_ignore(artifact_path)
        assert rc == 0, (
            f".gitignore should ignore {artifact_path!r} but git check-ignore "
            f"returned rc={rc}.\n"
            f"  stdout: {stdout!r}\n"
            f"  stderr: {stderr!r}\n"
            f"  → 检查 .gitignore 末尾 'R9 P1-013 治理' 块是否有对应规则。"
        )
        # 额外断言：stdout 包含 ".gitignore:" 行号 + 规则名（强语义）
        assert ".gitignore:" in stdout, (
            f"git check-ignore 返 rc=0 但 stdout 异常：{stdout!r}"
        )

    def test_check_ignore_does_not_depend_on_physical_existence(self):
        """组合守卫：``git check-ignore`` 对不存在的路径仍能正确判定 ignored。

        防止以后又有人把测试改回依赖 ``git status --ignored`` —— 后者对
        不存在的路径不报告 ignored，会让 12 条全 fail。

        实现方式：选一个**几乎肯定不存在**的路径（拼接随机后缀），
        ``git check-ignore`` 仍应判定为 ignored（因为 .gitignore 规则是
        通配符模式，不读文件系统）。
        """
        # 选一个明确会被忽略的"未来同类"路径字面量
        target = "data/eval_baseline_test_xyzzy_random_suffix.json"
        full = REPO_ROOT / target
        # 注意：本测试**不删不建**该文件 — 我们依赖"文件本身就不存在"
        # 也能让 check-ignore 正确判定 ignored 这件事。
        # 防御性：万一谁误创建了它，测试仍然要能 pass
        # （因为 .gitignore 规则覆盖了它，无论是否存在）
        rc, stdout, _ = _git_check_ignore(target)
        assert rc == 0, (
            f"git check-ignore 应判定 {target!r} 为 ignored（无论文件物理"
            f"是否存在），但返 rc={rc}。stdout={stdout!r}。"
            f"如果本测试挂，说明有人把测试改回依赖 `git status --ignored`，"
            f"或把 .gitignore 改坏了。"
        )
        # 对照：明显不会被忽略的随机路径字面量
        rc2, _, _ = _git_check_ignore("definitely_not_ignored_xyzzy_random.py")
        assert rc2 == 1, (
            f"git check-ignore 对无规则覆盖的随机路径应返 rc=1，"
            f"实际 rc={rc2}（说明 git check-ignore 本身坏了，不是路径问题）。"
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
        rc, stdout, stderr = _git_check_ignore(filename)
        assert rc == 0, (
            f"{filename} 未被 .gitignore 覆盖；R9 P1-013 治理模式漏覆盖，"
            f"未来同类文件将作为 untracked 泄漏到 git status。"
        )
