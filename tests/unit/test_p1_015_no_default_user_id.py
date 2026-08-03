# -*- coding: utf-8 -*-
"""P1-015 守卫测试 — 27 处 `user_id: str = "default"` 签名默认值清理完成。

R6 判定命令 1 的使能机制：所有 backend insert/read 方法必须显式 user_id，
不再有 `"default"` 默认值做静默漏写的兜底。本文件三层防护：

1. 反射守卫 — 检查 SqliteBackend 的每个方法签名里都不能有 user_id 默认值
2. e2e 守卫 — 调一次 insert 不传 user_id 必须 TypeError
3. 静态 grep — 整库 services/ tools/ agents/ scripts/ crawler/ pages/ database/
   不准再出现 `user_id: str = "default"` / `user_id="default"` 形式的默认值签名

加新接口时这里必须跟着扩。新增 21+9 = 30 个公开方法都覆盖到。
"""
from __future__ import annotations

import inspect
import re
import sqlite3
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# 静态扫描范围 — 任何 production 代码
SCAN_DIRS = [
    REPO_ROOT / "services",
    REPO_ROOT / "tools",
    REPO_ROOT / "agents",
    REPO_ROOT / "scripts",
    REPO_ROOT / "crawler",
    REPO_ROOT / "pages",
    REPO_ROOT / "database",
]

# 禁止的签名模式（参数默认值 = "default" / None）
FORBIDDEN_SIGNATURE_PATTERNS = [
    re.compile(r'user_id\s*:\s*str\s*=\s*["\']default["\']'),
    re.compile(r'user_id\s*:\s*Optional\[str\]\s*=\s*None'),
    re.compile(r'user_id\s*:\s*str\s*\|\s*None\s*=\s*None'),
]


# ============================================================
# 1. 反射守卫：SqliteBackend 的每个公开方法签名都不能有 user_id 默认值
# ============================================================

# P1-015 白名单：这些方法允许 user_id 有默认值（系统级聚合/跨用户搜索，user_id 可选）
# 任何新增方法必须先确认是否需要加入白名单；不允许默默接受 user_id 默认值
USER_ID_OPTIONAL_WHITELIST = {
    "get_llm_usage_today",       # QuotaService.get_global_usage_today() — 全局聚合
    "list_audit_logs",           # 审计日志系统级查询 — 可选按用户过滤
    "vector_search",             # RAG 向量检索 — 跨用户召回
    "like_search_chunks",        # RAG 关键词检索 — 跨用户召回
}


def _collect_required_methods():
    """SqliteBackend 的公开方法（去掉 _ 开头的私有方法）。"""
    from database.backends.sqlite_backend import SqliteBackend
    return [
        name for name in dir(SqliteBackend)
        if not name.startswith("_") and callable(getattr(SqliteBackend, name))
    ]


@pytest.mark.parametrize("method_name", _collect_required_methods())
def test_sqlite_backend_method_signatures_no_default_user_id(method_name):
    """每个公开方法的 user_id 形参要么是 keyword-only `*, user_id: str`，
    要么是 positional `user_id: str`（无默认值）。绝不能有 = "default" / = None。

    白名单（USER_ID_OPTIONAL_WHITELIST）允许的例外：
    - 系统级聚合查询（get_llm_usage_today）
    - 审计日志系统级查询（list_audit_logs）
    - 跨用户 RAG 搜索（vector_search / like_search_chunks）
    """
    from database.backends.sqlite_backend import SqliteBackend

    method = getattr(SqliteBackend, method_name)
    sig = inspect.signature(method)
    user_id_param = sig.parameters.get("user_id")
    if user_id_param is None:
        pytest.skip(f"{method_name} 不接收 user_id（允许）")

    if method_name in USER_ID_OPTIONAL_WHITELIST:
        # 白名单方法允许 user_id 有默认值（Optional[str] = None）
        assert user_id_param.default is None, (
            f"白名单方法 {method_name} 的 user_id 默认值必须为 None"
        )
        return

    # 非白名单方法：必须没有默认值
    assert user_id_param.default is inspect.Parameter.empty, (
        f"SqliteBackend.{method_name} 的 user_id 不应有默认值 "
        f"(actual default={user_id_param.default!r}) — "
        f"加白名单请在 USER_ID_OPTIONAL_WHITELIST 写明原因"
    )


# ============================================================
# 2. e2e 守卫：每个 insert 方法不传 user_id 必须 TypeError
# ============================================================

def _make_tmp_db(tmp_path):
    """最小 tmp_db：直接 sqlite，模拟 SqliteBackend 接口。"""
    from database.backends.sqlite_backend import SqliteBackend
    db_path = tmp_path / "guard.db"
    return SqliteBackend(db_path=str(db_path))


def test_insert_jd_without_user_id_raises_typeerror(tmp_path):
    """insert_jd 是 keyword-only `*, user_id: str`，调用方漏写必须 TypeError。"""
    db = _make_tmp_db(tmp_path)
    with pytest.raises(TypeError):
        db.insert_jd({"url": "https://x", "title": "t", "company": "c"})


def test_insert_resume_without_user_id_raises_typeerror(tmp_path):
    db = _make_tmp_db(tmp_path)
    with pytest.raises(TypeError):
        db.insert_resume({"name": "L"})


def test_insert_match_without_user_id_raises_typeerror(tmp_path):
    db = _make_tmp_db(tmp_path)
    with pytest.raises(TypeError):
        db.insert_match({"resume_id": "r1", "jd_id": "j1", "score": 80})


def test_insert_optimization_without_user_id_raises_typeerror(tmp_path):
    db = _make_tmp_db(tmp_path)
    with pytest.raises(TypeError):
        db.insert_optimization({"jd_id": "j", "section": "skills"})


def test_insert_chunk_without_user_id_raises_typeerror(tmp_path):
    db = _make_tmp_db(tmp_path)
    with pytest.raises(TypeError):
        db.insert_chunk({"jd_id": "j", "chunk_index": 0, "chunk_text": "t"})


def test_insert_chunks_batch_without_user_id_raises_typeerror(tmp_path):
    db = _make_tmp_db(tmp_path)
    with pytest.raises(TypeError):
        db.insert_chunks_batch("j", [{"chunk_text": "t"}])


def test_insert_llm_call_without_user_id_raises_typeerror(tmp_path):
    db = _make_tmp_db(tmp_path)
    with pytest.raises(TypeError):
        db.insert_llm_call({"model": "m", "operation": "o"})


def test_insert_audit_log_without_user_id_raises_typeerror(tmp_path):
    db = _make_tmp_db(tmp_path)
    with pytest.raises(TypeError):
        db.insert_audit_log({"action": "a", "target_table": "t"})


def test_insert_quality_check_without_user_id_raises_typeerror(tmp_path):
    db = _make_tmp_db(tmp_path)
    with pytest.raises(TypeError):
        db.insert_quality_check({"check_type": "t", "score": 1})


def test_insert_rewrite_history_without_user_id_raises_typeerror(tmp_path):
    db = _make_tmp_db(tmp_path)
    with pytest.raises(TypeError):
        db.insert_rewrite_history({"resume_id": "r", "operation": "rewrite"})


def test_insert_jd_structured_without_user_id_raises_typeerror(tmp_path):
    db = _make_tmp_db(tmp_path)
    with pytest.raises(TypeError):
        db.insert_jd_structured({"session_key": "s", "draft": "{}"})


# ============================================================
# 3. 静态 grep 守卫：production 代码禁止 user_id 默认值签名
# ============================================================

def _scan_production_code():
    """遍历 production 代码目录，收集所有 .py 文件。"""
    py_files = []
    for d in SCAN_DIRS:
        if not d.exists():
            continue
        for p in d.rglob("*.py"):
            py_files.append(p)
    return py_files


def test_no_default_user_id_in_production_signatures():
    """整库 production 代码（services/ tools/ agents/ scripts/ crawler/ pages/ database/）
    禁止再出现 user_id 默认值为 "default" / None 的签名。

    例外（白名单）：4 个系统级方法允许 user_id = None 默认值
    （get_llm_usage_today / list_audit_logs / vector_search / like_search_chunks）。
    """
    violations = []
    for py in _scan_production_code():
        text = py.read_text(encoding="utf-8")
        # 只检查函数/方法签名（行内含 `def ` 或 `async def `）
        for line_no, line in enumerate(text.splitlines(), 1):
            if "def " not in line:
                continue
            for pat in FORBIDDEN_SIGNATURE_PATTERNS:
                if pat.search(line):
                    # 检查是否在白名单方法中（function name 在 `def ` 之后）
                    m = re.search(r'def\s+(\w+)', line)
                    fname = m.group(1) if m else ""
                    if fname in USER_ID_OPTIONAL_WHITELIST:
                        continue  # 系统级聚合/跨用户搜索允许
                    rel = py.relative_to(REPO_ROOT)
                    violations.append(f"{rel}:{line_no}: {line.strip()}")
    assert not violations, (
        "P1-015 守卫失败 — 以下签名有 user_id 默认值:\n  "
        + "\n  ".join(violations)
    )


# ============================================================
# 4. 强一致性：StructuredJD 解析层不再带 user_id（防 P0-008 复发）
# ============================================================

def test_structured_jd_to_db_dict_does_not_carry_user_id():
    """P1-015 根因修复：StructuredJD 解析层不返回 user_id，强制 caller 盖印。
    防止 "default" 静默漏写通过 dict.get("user_id", "default") 复活。
    """
    from services.jd_parser import StructuredJD

    jd = StructuredJD(
        source="text",
        raw_text="x",
        company="c",
        title="t",
    )
    d = jd.to_db_dict()
    assert "user_id" not in d, (
        f"StructuredJD.to_db_dict() 不应携带 user_id（防 P0-008 复发）: {d}"
    )


def test_structured_jd_dataclass_has_no_user_id_field():
    """解析层 dataclass 字段里也不能有 user_id。"""
    from dataclasses import fields
    from services.jd_parser import StructuredJD

    field_names = {f.name for f in fields(StructuredJD)}
    assert "user_id" not in field_names, (
        f"StructuredJD 字段不应含 user_id（防 P0-008 复发）: {field_names}"
    )