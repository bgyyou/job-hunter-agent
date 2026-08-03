# -*- coding: utf-8 -*-
"""P1-002 回归：smart_collector 导入链路走 v2 统一库，不回潮到 v1 KnowledgeBase。

覆盖两层：
- 静态守卫：源码里不得再出现 v1 KnowledgeBase，必须出现 v2 落库 API
- 端到端：导入的 JD 能被 Flow B / JD 库的 list_visible_jds 看到（数据流通）
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from services.jd_library_service import list_visible_jds

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "collectors" / "import_collected.py"

USER_ID = "p1002-user"


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


def test_import_collected_no_longer_imports_v1_knowledge_base():
    """v1 KnowledgeBase 引用必须清零 —— 它写的是多 DB 文件，与 jobhunter_v2.db 不互通。"""
    imported = _imported_symbols(SCRIPT)
    assert "KnowledgeBase" not in imported
    assert "tools.knowledge_base" not in imported


def test_import_collected_uses_v2_persistence_api():
    """必须走 v2 的 insert_user_jd + embed_and_store_jd_chunks（与 crawler/pipeline 同路径）。"""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "insert_user_jd" in src
    assert "embed_and_store_jd_chunks" in src


# ---------- 端到端 ----------

@pytest.fixture
def collected_dir(tmp_path, monkeypatch):
    """伪造 ~/.job_hunter/collected_jds 并塞 2 个 collector 产物。"""
    home = tmp_path / "home"
    d = home / ".job_hunter" / "collected_jds"
    d.mkdir(parents=True)
    for i, title in enumerate(["AI产品经理", "数据产品经理"], 1):
        (d / f"job_{i:03d}.json").write_text(
            json.dumps(
                {
                    "title": title,
                    "company": "CollectCorp",
                    "url": f"https://collected.example/job/{i}",
                    "raw_text": "负责 AI 产品规划，要求熟悉 LLM、RAG 和 Agent 工程实践。",
                    "saved_at": "2026-08-04T00:00:00",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return d


def test_import_writes_into_v2_db_and_moves_files(tmp_db, collected_dir, mock_embedder, monkeypatch):
    import scripts.collectors.import_collected as mod

    monkeypatch.setattr(mod, "get_db", lambda: tmp_db)
    n = mod.import_collected_jobs(USER_ID)

    assert n == 2
    # 导入过的文件被挪进 imported/，重跑不会重复导入
    assert not list(collected_dir.glob("job_*.json"))
    assert len(list((collected_dir / "imported").glob("job_*.json"))) == 2


def test_imported_jds_are_visible_to_flow_b(tmp_db, collected_dir, mock_embedder, monkeypatch):
    """P1-002 的核心症状：导入后 Flow B 的 list_visible_jds 看得到才算数据流通。"""
    import scripts.collectors.import_collected as mod

    monkeypatch.setattr(mod, "get_db", lambda: tmp_db)
    mod.import_collected_jobs(USER_ID)

    visible = list_visible_jds(tmp_db, USER_ID)
    titles = {row["title"] for row in visible}

    assert "AI产品经理" in titles
    assert "数据产品经理" in titles
    assert all(row["source"] == "smart_collector" for row in visible)

    # 归属正确：别的用户看不到（私有 JD，is_public=0）
    assert list_visible_jds(tmp_db, "someone-else") == []
