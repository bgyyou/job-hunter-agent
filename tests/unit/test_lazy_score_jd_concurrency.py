# -*- coding: utf-8 -*-
"""M-v4-2 P1-001: 懒评分并发 race 治理回归测试。

零依赖：mock LLM 调用计数 + SQLite 真 ``compute_or_get_jd_quality`` 验证。"""
from __future__ import annotations

import importlib
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

import web_app  # noqa: E402
page_mod_1 = importlib.import_module('pages.07_📚_JD_Library')


def _row(**overrides):
    base = {
        "id": "jd-x",
        "source": "51job_batch",
        "platform": "51job",
        "title": "AI PM",
        "company": "ACME",
        "location": "深圳",
        "salary_str": "30-50K",
        "industry_tag": "互联网",
        "function_tag": "产品",
        "position_tag": "AI产品经理",
        "parsed_sections": {"requirements": ["LLM", "RAG", "Python"]},
        "tags": ["LLM", "RAG"],
        "crawled_at": "2026-07-04T00:00:00+00:00",
        "quality_score": None,
        "quality_checked_at": None,
    }
    base.update(overrides)
    return base


def _seed_jd(tmp_db, row, url_extra=""):
    return tmp_db.insert_jd(
        {
            "url": f"https://example.com/test-cas-{row['id']}{url_extra}",
            "title": row["title"],
            "company": row["company"],
            "source": row["source"],
            "platform": row["platform"],
            "raw_text": "this is a " * 200,
            "parsed_sections": row["parsed_sections"],
            "tags": row["tags"],
            "industry_tag": row["industry_tag"],
            "crawled_at": row["crawled_at"],
        },
        user_id="test",
    )


def test_quality_checked_at_column_exists(tmp_db):
    """M11 列已存在；CAS 写可读。"""
    jd_id = _seed_jd(tmp_db, _row(id="cols"))
    fresh = tmp_db.get_jd(jd_id)
    assert "quality_checked_at" in fresh
    assert fresh["quality_checked_at"] is None


def test_concurrent_lazy_score_only_one_llm_call(tmp_db, monkeypatch):
    """10 个并发线程访问同一未评分 JD → compute_jd_quality 调用 = 1。

    模拟场景：streamlit 主线程 + 后台 cron 同时打开同一未评分 JD，
    没锁会各算一次 = 10 次 LLM 调用；有锁只算 1 次。"""
    from services import jd_quality_service as qmod

    jd_id = _seed_jd(tmp_db, _row(id="race"))
    fetched = tmp_db.get_jd(jd_id)

    call_count = 0
    count_lock = threading.Lock()
    hold_compute = threading.Event()  # 让"被算中的那 1 次"停留足够久

    def slow_compute(jd, **_):
        nonlocal call_count
        with count_lock:
            call_count += 1
        # 让本线程在 critical section 里停住一秒，逼迫其它线程排队
        hold_compute.wait(timeout=3.0)
        return {"composite": 0.77, "breakdown": {}}

    monkeypatch.setattr(qmod, "compute_jd_quality", slow_compute)

    def worker():
        return page_mod_1._lazy_score_jd(tmp_db, fetched)

    barrier = threading.Barrier(10)

    def go():
        barrier.wait()  # 同时冲入
        return worker()

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(go) for _ in range(10)]
        # 等 0.3s 确保某个线程已抢到锁开始 compute，然后放开它
        import time
        time.sleep(0.3)
        hold_compute.set()
        results = [f.result() for f in futures]

    assert call_count == 1, (
        f"应有 1 次 LLM 调用，实际 {call_count} 次 — 同进程锁没拦住并发"
    )
    # 全部线程拿到同样的 score（race 后无脏读 / 闪烁）
    assert all(r == 0.77 for r in results), f"score 闪烁: {results}"


def test_cas_rejects_stale_version_write(tmp_db):
    """expected_checked_at 与 DB 实际不符 → CAS 拒绝，返回 False。"""
    jd_id = _seed_jd(tmp_db, _row(id="stale"))
    # 直接走底层 CAS: 期望 DB 当前为 NULL（未评分）
    wrote_initial = tmp_db.update_jd_quality_score_cas(
        jd_id, 0.5, "2026-08-04T01:00:00+00:00", expected_checked_at=None,
    )
    assert wrote_initial is True, "首次应写入成功"

    # 再用同样的 expected=None 写 — DB 已有 quality_checked_at 非空，拒绝
    wrote_second = tmp_db.update_jd_quality_score_cas(
        jd_id, 0.99, "2026-08-04T02:00:00+00:00", expected_checked_at=None,
    )
    assert wrote_second is False, "已评分的行不应被 expected=None 覆盖"

    fresh = tmp_db.get_jd(jd_id)
    assert fresh["quality_score"] == 0.5, (
        f"二次写被拒失败: score={fresh['quality_score']}"
    )


def test_compute_or_get_calls_compute_only_once(tmp_db, monkeypatch):
    """compute_or_get_jd_quality 多次调用同一 jd_id → ``compute_fn`` 仅执行 1 次。"""
    from services import jd_quality_service as qmod

    jd_id = _seed_jd(tmp_db, _row(id="cached"))
    calls = []

    def fake_compute(jd, **_):
        calls.append(jd["id"])
        return {"composite": 0.55, "breakdown": {}}

    monkeypatch.setattr(qmod, "compute_jd_quality", fake_compute)

    def _compute():
        from services.jd_quality_service import compute_jd_quality
        return compute_jd_quality({"id": jd_id})["composite"]

    # 第一次：本线程 compute 并写
    s1 = tmp_db.compute_or_get_jd_quality(jd_id, _compute)
    # 第二次：DB 已有 score → 直接返回，compute 不再被调
    s2 = tmp_db.compute_or_get_jd_quality(jd_id, _compute)
    s3 = tmp_db.compute_or_get_jd_quality(jd_id, _compute)

    assert s1 == s2 == s3 == 0.55
    assert len(calls) == 1, f"预期 1 次 compute 实际 {len(calls)}: {calls}"


def test_lazy_score_returns_existing_when_already_scored(tmp_db, monkeypatch):
    """``quality_score`` 已在 jd dict 里时 → 直接返回，不调 compute。"""
    from services import jd_quality_service as qmod

    calls = []
    monkeypatch.setattr(
        qmod, "compute_jd_quality",
        lambda *_a, **_k: calls.append(1) or {"composite": 0.11, "breakdown": {}},
    )

    row = _row(id="fast", quality_score=0.93, quality_checked_at="t0")
    score = page_mod_1._lazy_score_jd(tmp_db, row)

    assert score == 0.93
    assert calls == [], f"快路径不应调 compute，实际调了 {len(calls)} 次"
