# -*- coding: utf-8 -*-
"""M-v4-1 Ops 可观测性面板的单元测试。

3 条核心测试（任务验收要求）：
1. SQL 聚合正确性：插 N 条数据 → judge_mock_fallback_rate / llm_success_rate /
   retrieval_latency / top_failure_cases 返回预期比例与排序。
2. 空数据库 graceful：全新 tmp_db 上调用所有 4 个 panel → 不抛异常、shape 一致。
3. 颜色阈值逻辑：threshold_color(0.05)=='yellow'，threshold_color(0.10)=='red'，
   threshold_color(0.02)=='green'，threshold_color(None)=='green'。
"""
from __future__ import annotations

import pytest

from services.ops_metrics import (
    MOCK_FALLBACK_RED,
    MOCK_FALLBACK_YELLOW,
    judge_mock_fallback_rate,
    llm_success_rate,
    retrieval_latency,
    threshold_color,
    top_failure_cases,
)


# ---------------------------------------------------------------------------
# 阈值逻辑（纯函数，无 DB 依赖）
# ---------------------------------------------------------------------------
class TestThresholdColor:
    def test_below_yellow_is_green(self):
        assert threshold_color(0.00) == "green"
        assert threshold_color(0.01) == "green"
        assert threshold_color(MOCK_FALLBACK_YELLOW - 0.001) == "green"

    def test_yellow_band(self):
        # 区间 [3%, 10%) → yellow；边界 10% 是 red，3% 是 green
        assert threshold_color(MOCK_FALLBACK_YELLOW) == "yellow"
        assert threshold_color(0.05) == "yellow"
        assert threshold_color(MOCK_FALLBACK_RED - 0.001) == "yellow"

    def test_red_band(self):
        assert threshold_color(MOCK_FALLBACK_RED) == "red"
        assert threshold_color(0.50) == "red"
        assert threshold_color(1.00) == "red"

    def test_none_and_negative_become_green(self):
        # 0 调用 → rate=None/0 → 绿（鼓励"还没数据不要慌"语义）
        assert threshold_color(None) == "green"
        assert threshold_color(0) == "green"
        assert threshold_color(-0.5) == "green"

    def test_threshold_constants_match_design(self):
        # 文档阈值：红 ≥ 10%，黄 3-10%，绿 < 3%
        assert MOCK_FALLBACK_RED == pytest.approx(0.10)
        assert MOCK_FALLBACK_YELLOW == pytest.approx(0.03)


# ---------------------------------------------------------------------------
# 空数据库 graceful
# ---------------------------------------------------------------------------
class TestEmptyDatabase:
    """全新 tmp_db 没有任何 quality_checks / llm_calls → 4 个 panel 都返回 shape 一致。"""

    def test_judge_mock_fallback_rate_empty(self, tmp_db):
        r = judge_mock_fallback_rate(tmp_db)
        assert r["total_judge_calls"] == 0
        assert r["mock_fallback_calls"] == 0
        assert r["mock_fallback_rate"] == 0.0
        assert r["by_day"] == []
        # 颜色是绿（rate=0）
        assert threshold_color(r["mock_fallback_rate"]) == "green"

    def test_retrieval_latency_empty(self, tmp_db):
        r = retrieval_latency(tmp_db)
        assert r["count"] == 0
        assert r["avg_ms"] == 0.0
        # SQLite 无 percentile_cont → p95 永远 None（PG 才支持）
        assert r["p95_ms"] is None
        assert r["by_phase"] == []

    def test_llm_success_rate_empty(self, tmp_db):
        r = llm_success_rate(tmp_db)
        assert r["total"] == 0
        assert r["success"] == 0
        assert r["error"] == 0
        assert r["cache_hit"] == 0
        assert r["success_rate"] == 0.0
        assert r["error_rate"] == 0.0

    def test_top_failure_cases_empty(self, tmp_db):
        assert top_failure_cases(tmp_db) == []


# ---------------------------------------------------------------------------
# SQL 聚合正确性
# ---------------------------------------------------------------------------
def _seed_one_judge_call(db, *, operation="judge_batch", status="success",
                         error_message=None, created_at=None):
    """插 1 条 llm_calls 行。"""
    db.insert_llm_call({
        "model": "test-model",
        "operation": operation,
        "latency_ms": 100,
        "status": status,
        "error_message": error_message,
    })


def _seed_one_quality_check(db, *, check_type="retrieval", details=None):
    db.insert_quality_check({
        "check_type": check_type,
        "target_table": "jds",
        "target_id": "x",
        "score": 1.0,
        "details": details or {"latency_ms": 200},
    })


class TestJudgeMockFallbackAggregation:
    def test_seven_of_ten_judge_fell_back_to_mock(self, tmp_db):
        # 10 次 judge 调用：3 次真成功，7 次 mock fallback
        for _ in range(3):
            _seed_one_judge_call(tmp_db, status="success", error_message=None)
        for _ in range(7):
            _seed_one_judge_call(
                tmp_db, status="error",
                error_message="FALLBACK_MOCK (err: 429 rate limit)",
            )
        r = judge_mock_fallback_rate(tmp_db)
        assert r["total_judge_calls"] == 10
        assert r["mock_fallback_calls"] == 7
        assert r["mock_fallback_rate"] == pytest.approx(0.70)
        # 70% ≥ 10% → 红
        assert threshold_color(r["mock_fallback_rate"]) == "red"
        # by_day 至少 1 天
        assert len(r["by_day"]) == 1
        assert r["by_day"][0]["total"] == 10
        assert r["by_day"][0]["mock"] == 7

    def test_zero_fallback_is_green(self, tmp_db):
        for _ in range(5):
            _seed_one_judge_call(tmp_db, status="success")
        r = judge_mock_fallback_rate(tmp_db)
        assert r["mock_fallback_rate"] == 0.0
        assert threshold_color(r["mock_fallback_rate"]) == "green"

    def test_non_judge_operations_excluded(self, tmp_db):
        # 'analyze' 不是 judge，不应被计入 judge rate
        for _ in range(5):
            _seed_one_judge_call(tmp_db, operation="analyze",
                                 status="error", error_message="FALLBACK_MOCK (x)")
        r = judge_mock_fallback_rate(tmp_db)
        assert r["total_judge_calls"] == 0
        assert r["mock_fallback_calls"] == 0


class TestRetrievalLatencyAggregation:
    def test_avg_and_count(self, tmp_db):
        for ms in [100, 200, 300, 400, 500]:
            _seed_one_quality_check(tmp_db, details={"latency_ms": ms})
        r = retrieval_latency(tmp_db)
        assert r["count"] == 5
        assert r["avg_ms"] == pytest.approx(300.0)
        # SQLite 无 percentile_cont
        assert r["p95_ms"] is None

    def test_null_latency_excluded(self, tmp_db):
        # details.latency_ms 缺失 → 不应参与平均
        _seed_one_quality_check(tmp_db, details={"latency_ms": 1000})
        _seed_one_quality_check(tmp_db, details={"other_field": "x"})
        r = retrieval_latency(tmp_db)
        assert r["count"] == 1
        assert r["avg_ms"] == pytest.approx(1000.0)

    def test_by_phase_groups_by_rerank_marker(self, tmp_db):
        _seed_one_quality_check(tmp_db, details={"latency_ms": 100, "rerank": "on"})
        _seed_one_quality_check(tmp_db, details={"latency_ms": 300, "rerank": "on"})
        _seed_one_quality_check(tmp_db, details={"latency_ms": 200, "rerank": "off"})
        r = retrieval_latency(tmp_db)
        # 按出现次数倒序：on(2) 在前
        assert r["by_phase"][0]["phase"] == "on"
        assert r["by_phase"][0]["count"] == 2
        assert r["by_phase"][0]["avg_ms"] == pytest.approx(200.0)
        assert r["by_phase"][1]["phase"] == "off"
        assert r["by_phase"][1]["avg_ms"] == pytest.approx(200.0)


class TestLlmSuccessRateAggregation:
    def test_basic_mix(self, tmp_db):
        for _ in range(7):
            _seed_one_judge_call(tmp_db, operation="analyze", status="success")
        for _ in range(2):
            _seed_one_judge_call(tmp_db, operation="analyze", status="error",
                                 error_message="api_error")
        for _ in range(1):
            _seed_one_judge_call(tmp_db, operation="analyze", status="cache_hit")
        r = llm_success_rate(tmp_db)
        assert r["total"] == 10
        assert r["success"] == 7
        assert r["error"] == 2
        assert r["cache_hit"] == 1
        # success_rate 把 cache_hit 也算成功：(7+1)/10 = 0.8
        assert r["success_rate"] == pytest.approx(0.8)
        assert r["error_rate"] == pytest.approx(0.2)

    def test_all_success(self, tmp_db):
        for _ in range(3):
            _seed_one_judge_call(tmp_db, status="success")
        r = llm_success_rate(tmp_db)
        assert r["success_rate"] == 1.0
        assert r["error_rate"] == 0.0


class TestTopFailureCasesAggregation:
    def test_grouped_by_operation_and_error_type(self, tmp_db):
        # 5× analyze+rate_limit, 3× judge_batch+timeout, 1× analyze+api_error
        for _ in range(5):
            tmp_db.insert_llm_call({
                "model": "m", "operation": "analyze", "status": "error",
                "error_type": "rate_limit", "latency_ms": 10,
            })
        for _ in range(3):
            tmp_db.insert_llm_call({
                "model": "m", "operation": "judge_batch", "status": "error",
                "error_type": "timeout", "latency_ms": 10,
            })
        tmp_db.insert_llm_call({
            "model": "m", "operation": "analyze", "status": "error",
            "error_type": "api_error", "latency_ms": 10,
        })
        # 非 error 不计入
        tmp_db.insert_llm_call({
            "model": "m", "operation": "analyze", "status": "success",
            "latency_ms": 10,
        })

        rows = top_failure_cases(tmp_db)
        # 第一名：analyze+rate_limit (5)
        assert rows[0]["operation"] == "analyze"
        assert rows[0]["error_type"] == "rate_limit"
        assert rows[0]["count"] == 5
        # 第二名：judge_batch+timeout (3)
        assert rows[1]["operation"] == "judge_batch"
        assert rows[1]["count"] == 3
        # 第三名：analyze+api_error (1)
        assert rows[2]["operation"] == "analyze"
        assert rows[2]["error_type"] == "api_error"
        assert rows[2]["count"] == 1

    def test_respects_limit(self, tmp_db):
        for i in range(5):
            tmp_db.insert_llm_call({
                "model": "m", "operation": f"op_{i}", "status": "error",
                "error_type": "x", "latency_ms": 10,
            })
        rows = top_failure_cases(tmp_db, limit=2)
        assert len(rows) == 2
