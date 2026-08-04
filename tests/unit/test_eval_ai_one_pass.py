from __future__ import annotations

import json

import pytest

from eval.ai_one_pass import (
    EvaluationRecord,
    GenerationVerdict,
    compute_ai_one_pass_metrics,
    load_evaluation_records,
)


def _record(index: int, *, human_pass: bool, judge_pass: bool = True, is_mock: bool = False):
    scores = {
        "factual_consistency": 5,
        "role_alignment": 4,
        "completeness": 4,
        "format_quality": 5,
    }
    return EvaluationRecord(
        query_id=f"resume-{index:03d}",
        judge=GenerationVerdict(
            one_pass=judge_pass,
            scores=scores,
            reason="无需重新生成" if judge_pass else "关键经历缺失",
            is_mock=is_mock,
        ),
        human_one_pass=human_pass,
    )


def test_human_pass_rate_is_the_product_score_for_complete_50_sample_baseline():
    records = [_record(index, human_pass=index < 35) for index in range(50)]

    metrics = compute_ai_one_pass_metrics(records)

    assert metrics.sample_count == 50
    assert metrics.human_rated_count == 50
    assert metrics.human_pass_rate == 0.7
    assert metrics.product_score == 7.0
    assert metrics.valid_for_review is True


def test_incomplete_human_ratings_cannot_be_filled_into_review():
    records = [_record(index, human_pass=True) for index in range(49)]
    records.append(
        EvaluationRecord(
            query_id="resume-049",
            judge=records[0].judge,
            human_one_pass=None,
        )
    )

    metrics = compute_ai_one_pass_metrics(records)

    assert metrics.human_rated_count == 49
    assert metrics.product_score is None
    assert metrics.valid_for_review is False


def test_mock_fallback_rate_at_three_percent_or_more_invalidates_baseline():
    records = [_record(index, human_pass=True, is_mock=index < 2) for index in range(50)]

    metrics = compute_ai_one_pass_metrics(records)

    assert metrics.mock_fallback_rate == 0.04
    assert metrics.product_score is None
    assert metrics.valid_for_review is False


def test_empty_baseline_has_zero_diagnostics_and_no_product_score():
    metrics = compute_ai_one_pass_metrics([])

    assert metrics.sample_count == 0
    assert metrics.judge_pass_rate == 0.0
    assert metrics.dimension_averages["factual_consistency"] == 0.0
    assert metrics.product_score is None


def test_verdict_rejects_missing_or_out_of_range_dimensions():
    with pytest.raises(ValueError, match="missing score dimensions"):
        GenerationVerdict(one_pass=True, scores={}, reason="", is_mock=False)

    with pytest.raises(ValueError, match="scores must be between 1 and 5"):
        GenerationVerdict(
            one_pass=True,
            scores={
                "factual_consistency": 6,
                "role_alignment": 4,
                "completeness": 4,
                "format_quality": 4,
            },
            reason="",
            is_mock=False,
        )


def test_jsonl_loader_reads_ratings_and_reports_bad_line(tmp_path):
    valid_path = tmp_path / "valid.jsonl"
    valid_path.write_text(
        json.dumps(
            {
                "query_id": "resume-001",
                "judge": {
                    "one_pass": True,
                    "scores": {
                        "factual_consistency": 5,
                        "role_alignment": 4,
                        "completeness": 4,
                        "format_quality": 5,
                    },
                    "reason": "可直接使用",
                    "is_mock": False,
                },
                "human_one_pass": True,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    records = load_evaluation_records(valid_path)

    assert records[0].query_id == "resume-001"
    assert records[0].human_one_pass is True

    invalid_path = tmp_path / "invalid.jsonl"
    invalid_path.write_text('{"query_id": "resume-002", "judge": {}}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSONL at line 1"):
        load_evaluation_records(invalid_path)
