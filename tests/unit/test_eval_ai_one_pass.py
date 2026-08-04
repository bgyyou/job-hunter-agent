from __future__ import annotations

from eval.ai_one_pass import EvaluationRecord, GenerationVerdict, compute_ai_one_pass_metrics


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
