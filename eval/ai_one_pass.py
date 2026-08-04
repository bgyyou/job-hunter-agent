from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Optional, Sequence


SCORE_DIMENSIONS = (
    "factual_consistency",
    "role_alignment",
    "completeness",
    "format_quality",
)
MIN_BASELINE_SAMPLES = 50
MAX_MOCK_FALLBACK_RATE = 0.03


@dataclass(frozen=True)
class GenerationVerdict:
    one_pass: bool
    scores: Mapping[str, int]
    reason: str
    is_mock: bool = False

    def __post_init__(self) -> None:
        missing = set(SCORE_DIMENSIONS) - set(self.scores)
        if missing:
            raise ValueError(f"missing score dimensions: {sorted(missing)}")
        invalid = {
            name: self.scores[name]
            for name in SCORE_DIMENSIONS
            if not 1 <= self.scores[name] <= 5
        }
        if invalid:
            raise ValueError(f"scores must be between 1 and 5: {invalid}")


@dataclass(frozen=True)
class EvaluationRecord:
    query_id: str
    judge: GenerationVerdict
    human_one_pass: Optional[bool]


@dataclass(frozen=True)
class AIOnePassMetrics:
    sample_count: int
    human_rated_count: int
    human_pass_rate: Optional[float]
    judge_pass_rate: float
    mock_fallback_rate: float
    dimension_averages: Mapping[str, float]
    product_score: Optional[float]
    valid_for_review: bool


def compute_ai_one_pass_metrics(records: Sequence[EvaluationRecord]) -> AIOnePassMetrics:
    sample_count = len(records)
    human_rated = [record.human_one_pass for record in records if record.human_one_pass is not None]
    human_rated_count = len(human_rated)
    human_pass_rate = (
        round(sum(human_rated) / human_rated_count, 4) if human_rated_count else None
    )
    judge_pass_rate = (
        round(sum(record.judge.one_pass for record in records) / sample_count, 4)
        if sample_count
        else 0.0
    )
    mock_fallback_rate = (
        round(sum(record.judge.is_mock for record in records) / sample_count, 4)
        if sample_count
        else 0.0
    )
    dimension_averages = {
        dimension: round(
            sum(record.judge.scores[dimension] for record in records) / sample_count,
            2,
        )
        if sample_count
        else 0.0
        for dimension in SCORE_DIMENSIONS
    }
    valid_for_review = (
        sample_count >= MIN_BASELINE_SAMPLES
        and human_rated_count == sample_count
        and mock_fallback_rate < MAX_MOCK_FALLBACK_RATE
    )
    product_score = (
        round(human_pass_rate * 10, 1)
        if valid_for_review and human_pass_rate is not None
        else None
    )
    return AIOnePassMetrics(
        sample_count=sample_count,
        human_rated_count=human_rated_count,
        human_pass_rate=human_pass_rate,
        judge_pass_rate=judge_pass_rate,
        mock_fallback_rate=mock_fallback_rate,
        dimension_averages=dimension_averages,
        product_score=product_score,
        valid_for_review=valid_for_review,
    )


def _load_verdict(data: Mapping[str, object]) -> GenerationVerdict:
    raw_scores = data.get("scores")
    if not isinstance(raw_scores, dict):
        raise ValueError("judge.scores must be an object")
    return GenerationVerdict(
        one_pass=bool(data.get("one_pass")),
        scores={name: int(raw_scores[name]) for name in SCORE_DIMENSIONS},
        reason=str(data.get("reason", "")),
        is_mock=bool(data.get("is_mock", False)),
    )


def load_evaluation_records(path: Path) -> list[EvaluationRecord]:
    records: list[EvaluationRecord] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                judge = data["judge"]
                if not isinstance(judge, dict):
                    raise ValueError("judge must be an object")
                human_one_pass = data.get("human_one_pass")
                if human_one_pass is not None and not isinstance(human_one_pass, bool):
                    raise ValueError("human_one_pass must be true, false, or null")
                records.append(
                    EvaluationRecord(
                        query_id=str(data["query_id"]),
                        judge=_load_verdict(judge),
                        human_one_pass=human_one_pass,
                    )
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"invalid JSONL at line {line_number}: {exc}") from exc
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute AI resume one-pass product metrics")
    parser.add_argument("ratings", type=Path)
    args = parser.parse_args()

    metrics = compute_ai_one_pass_metrics(load_evaluation_records(args.ratings))
    print(json.dumps(asdict(metrics), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
