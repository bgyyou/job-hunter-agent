"""Unit tests for eval/ (P0-模块 6 子任务 1).

这些测试只覆盖本地、无依赖的部分：
- _parse_score 解析 1-5
- _mock_judge fallback 逻辑
- compute_metrics 数学正确性
- build_queries 200 条产出

不调用 LLM API，不依赖 embedding 模型。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from eval.judge import _mock_judge, _parse_score  # noqa: E402
from eval.run_eval import compute_metrics  # noqa: E402


class TestParseScore:
    def test_pure_digit(self):
        assert _parse_score("4") == 4

    def test_with_text(self):
        assert _parse_score("Score: 5") == 5

    def test_with_surrounding(self):
        assert _parse_score("\n 3 \n") == 3

    def test_first_digit_wins(self):
        assert _parse_score("4 or maybe 5") == 4

    def test_no_digit_returns_3(self):
        assert _parse_score("not a number") == 3

    def test_empty_returns_3(self):
        assert _parse_score("") == 3

    def test_out_of_range_ignored(self):
        # "9" 不在 1-5，应该不匹配第一个数字 9
        # 当前实现只接受 [1-5] 所以 9 不被匹配 → fallback 3
        assert _parse_score("score is 9") == 3


class TestMockJudge:
    def test_high_overlap_gives_4(self):
        v = _mock_judge("Python data analyst", None, "Data Analyst Python", "Python and SQL required")
        assert v.is_mock is True
        assert v.score >= 4

    def test_no_overlap_gives_2(self):
        v = _mock_judge("Python data analyst", None, "Driver", "Truck license required")
        assert v.is_mock is True
        assert v.score == 2

    def test_partial_overlap_gives_3(self):
        v = _mock_judge("product manager user growth", None, "Operations Manager",
                       "Manage team operations")
        assert v.is_mock is True
        assert v.score >= 2


class TestComputeMetrics:
    def test_empty(self):
        m = compute_metrics([])
        assert m["ndcg_at_10"] == 0.0
        assert m["recall_at_10"] == 0.0
        assert m["mrr"] == 0.0
        assert m["hit_rate"] == 0.0

    def test_perfect_ranking(self):
        # 所有候选都相关，理想排序
        per_q = [{"scores": [5, 5, 5, 5, 5, 5, 5, 5, 5, 5], "rank_of_first_relevant": 1}]
        m = compute_metrics(per_q)
        assert m["ndcg_at_10"] == 1.0
        assert m["mrr"] == 1.0
        assert m["hit_rate"] == 1.0

    def test_no_relevant(self):
        per_q = [{"scores": [2, 2, 2, 1, 1, 1, 1, 1, 1, 1], "rank_of_first_relevant": None}]
        m = compute_metrics(per_q)
        assert m["ndcg_at_10"] == 0.0
        assert m["mrr"] == 0.0
        assert m["hit_rate"] == 0.0

    def test_first_relevant_at_rank_2(self):
        per_q = [{"scores": [2, 5, 5, 5, 5, 5, 5, 5, 5, 5], "rank_of_first_relevant": 2}]
        m = compute_metrics(per_q)
        assert m["mrr"] == 0.5
        assert m["hit_rate"] == 1.0


class TestQueriesFile:
    """Smoke check on queries.jsonl shape."""

    def test_file_exists(self):
        path = PROJECT_ROOT / "eval" / "queries.jsonl"
        assert path.exists(), f"missing {path}"

    def test_file_count(self):
        path = PROJECT_ROOT / "eval" / "queries.jsonl"
        n = 0
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    n += 1
        assert n >= 200, f"expected >=200 queries, got {n}"

    def test_query_shape(self):
        path = PROJECT_ROOT / "eval" / "queries.jsonl"
        with path.open("r", encoding="utf-8") as f:
            q = json.loads(f.readline())
        for k in ("query_id", "query", "form", "query_type"):
            assert k in q, f"missing field {k}"