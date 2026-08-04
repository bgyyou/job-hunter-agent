from __future__ import annotations

from pathlib import Path

from eval.product_baseline import measure_draft_upgrade


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_v4_1_to_v4_2_preserves_all_flow_a_drafts():
    result = measure_draft_upgrade(
        repo_root=REPO_ROOT,
        old_ref="5b1897a",
        new_ref="482b0c7",
        sample_count=5,
    )

    assert result.old_schema_version == 16
    assert result.new_schema_version == 17
    assert result.sample_count == 5
    assert result.preserved_count == 5
    assert result.lost_draft_ids == ()
    assert result.score == 10.0
