# -*- coding: utf-8 -*-
"""PR4: live data snapshot — 测试 _live_snapshot_from_db 纯函数，避开 st.cache 全局。"""
from __future__ import annotations

import importlib
import pytest


@pytest.fixture
def fresh_webapp():
    import web_app
    importlib.reload(web_app)
    return web_app


def test_live_snapshot_returns_expected_keys(tmp_db, fresh_webapp):
    snap = fresh_webapp._live_snapshot_from_db(tmp_db)
    assert set(snap.keys()) == {"total", "new_week", "industries", "platforms"}
    for v in snap.values():
        assert isinstance(v, int)
        assert v >= 0


def test_live_snapshot_counts_inserted_jd(tmp_db, fresh_webapp):
    rows = [
        {"url": "https://x/1", "title": "t", "source": "51job_batch", "platform": "51job",
         "industry_tag": "互联网", "raw_text": "text " * 100},
        {"url": "https://x/2", "title": "t", "source": "jobsdb_batch", "platform": "jobsdb",
         "industry_tag": "金融", "raw_text": "text " * 100},
        {"url": "https://x/3", "title": "t", "source": "51job_batch", "platform": "51job",
         "industry_tag": "互联网", "raw_text": "text " * 100},
    ]
    for r in rows:
        tmp_db.insert_jd(r, user_id="test")

    snap = fresh_webapp._live_snapshot_from_db(tmp_db)
    assert snap["total"] == 3
    assert snap["platforms"] == 2
    assert snap["industries"] == 2


def test_live_snapshot_soft_deleted_excluded(tmp_db, fresh_webapp):
    jid = tmp_db.insert_jd({
        "url": "https://x/del",
        "title": "t",
        "source": "manual",
        "raw_text": "x",
    }, user_id="test")
    tmp_db.soft_delete_jd(jid)

    snap = fresh_webapp._live_snapshot_from_db(tmp_db)
    assert snap["total"] == 0


def test_live_snapshot_handles_null_platform_and_industry(tmp_db, fresh_webapp):
    """platform / industry_tag 为 NULL 的 JD 不计入去重计数。"""
    tmp_db.insert_jd({"url": "https://x/null", "title": "t", "source": "manual", "raw_text": "x"}, user_id="test")
    snap = fresh_webapp._live_snapshot_from_db(tmp_db)
    # total 仍计 1（只筛 deleted_at），platforms/industries 都是 0（NULL 不入 DISTINCT）
    assert snap["total"] == 1
    assert snap["platforms"] == 0
    assert snap["industries"] == 0
