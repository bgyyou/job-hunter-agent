# -*- coding: utf-8 -*-
"""P1-002b 回归：manual_collector 导入链路走 v2 统一库，不回潮到 v1 KnowledgeBase。

P1-002 已修 ``scripts/collectors/import_collected.py``；本文件覆盖
**同根因残留** ``scripts/collectors/manual_collector.py`` 的 ``import_to_v2``
（先前叫 ``import_to_knowledge_base``）。

覆盖两层：
- 静态守卫：源码里不得再出现 v1 ``KnowledgeBase`` / ``tools.knowledge_base``，
  必须出现 v2 落库 API（``db.insert_user_jd`` 字面量 / ``insert_user_jd`` import）
- 端到端：手动收集的 JD 经 ``import_to_v2`` 写入 v2 后能被 Flow B /
  JD 库的 ``list_visible_jds`` 看到（数据流通验证）
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from services.jd_library_service import list_visible_jds

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "collectors" / "manual_collector.py"

USER_ID = "p1002b-user"


# ---------- 静态守卫 ----------

def _imported_symbols(path: Path) -> set[str]:
    """收集文件里所有 import 的模块名与符号名（走 AST，不误伤注释/docstring）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
            names.update(a.name for a in node.names)
    return names


def test_manual_collector_no_longer_imports_v1_knowledge_base():
    """v1 KnowledgeBase 引用必须清零 —— 它写的是多 DB 文件，与 jobhunter_v2.db 不互通。

    这是 P1-002 同根因：smart_collector 已修，manual_collector 还在回潮。"""
    imported = _imported_symbols(SCRIPT)
    assert "KnowledgeBase" not in imported, (
        f"仍有 v1 KnowledgeBase 引用: {[n for n in imported if 'Knowledge' in n]}"
    )
    assert "tools.knowledge_base" not in imported


def test_manual_collector_uses_v2_db_insert_literal():
    """源码必须含 ``db.insert_user_jd`` 字面量（即调 ``insert_user_jd(db, ...)`` 落到 v2）。"""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "insert_user_jd" in src, "源码应调用 services.jd_library_service.insert_user_jd"
    # 直接 import 的形式也要有
    assert "embed_and_store_jd_chunks" in src


# ---------- 端到端 ----------

@pytest.fixture
def collected_dir(tmp_path, monkeypatch):
    """伪造 ``~/.job_hunter/collected_jds`` 并塞 2 个 manual_collector 产物。"""
    home = tmp_path / "home"
    d = home / ".job_hunter" / "collected_jds"
    d.mkdir(parents=True)
    for i, title in enumerate(["PM 主管", "高级数据分析师"], 1):
        (d / f"jd_{i:03d}.json").write_text(
            json.dumps(
                {
                    "title": title,
                    "company": "ManualCorp",
                    "url": f"https://manual.example/jd/{i}",
                    "raw_text": "负责产品规划与团队管理。要求 5 年以上产品经验，熟悉 LLM。",
                    "collected_at": "2026-08-04T01:00:00",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return d


def test_manual_import_writes_into_v2_db_and_moves_files(
    tmp_db, collected_dir, mock_embedder, monkeypatch,
):
    """``import_to_v2`` 把 ``jd_*.json`` 入库并挪进 ``imported/``，避免重跑重复入。"""
    import scripts.collectors.manual_collector as mod

    monkeypatch.setattr(mod, "get_db", lambda: tmp_db)
    n = mod.import_to_v2(USER_ID, collected_dir)

    assert n == 2
    assert not list(collected_dir.glob("jd_*.json")), "导入过的文件应被挪走"
    assert len(list((collected_dir / "imported").glob("jd_*.json"))) == 2


def test_manual_imported_jds_visible_to_flow_b(
    tmp_db, collected_dir, mock_embedder, monkeypatch,
):
    """P1-002b 的核心症状：手动 import 后 Flow B 的 ``list_visible_jds`` 看得到。"""
    import scripts.collectors.manual_collector as mod

    monkeypatch.setattr(mod, "get_db", lambda: tmp_db)
    mod.import_to_v2(USER_ID, collected_dir)

    visible = list_visible_jds(tmp_db, USER_ID)
    titles = {row["title"] for row in visible}

    assert "PM 主管" in titles
    assert "高级数据分析师" in titles
    assert all(row["source"] == "manual_collector" for row in visible)

    # 归属正确：别的用户看不到（私有 JD，is_public=0）
    assert list_visible_jds(tmp_db, "someone-else") == []
