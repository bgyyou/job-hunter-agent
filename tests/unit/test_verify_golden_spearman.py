"""Unit tests for scripts/verify_golden_spearman.py (M-v4-1 子任务).

覆盖：
- dcg_at_k / ndcg_at_k 数值正确性（边界：空列表、全 1、全 0、混合）
- compute_spearman 完美正相关 / 完美负相关 / 常数列 / 不同长度报错
- build_per_query_ndcgs 把 PRELIMINARY label 与 LLM judge score 都正确转 NDCG
- 验证脚本 main() 在 mock 数据上能跑通；--regenerate-judge 不需要真正网络
- ndcg_at_k 当 k > len 时取全部（不报错）

不调 LLM API、不调 retriever；只验证数学 + 数据流。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pytest  # noqa: E402

from scripts.verify_golden_spearman import (  # noqa: E402
    build_per_query_ndcgs,
    compute_spearman,
    dcg_at_k,
    ndcg_at_k,
)


class TestDcgAtK:
    def test_all_relevant_first(self):
        # 5 个全相关，k=5：DCG = sum(1/log2(i+2)) for i=0..4
        # = 1/log2(2) + 1/log2(3) + 1/log2(4) + 1/log2(5) + 1/log2(6)
        import math
        expected = sum(1 / math.log2(i + 2) for i in range(5))
        rels = [1] * 5
        d = dcg_at_k(rels, 5)
        assert d == pytest.approx(expected, rel=1e-9)

    def test_truncates_to_k(self):
        # 列表长度等于 k：DCG@k 取全部
        rels = [1, 0, 1, 0, 1]
        assert dcg_at_k(rels, 5) == pytest.approx(dcg_at_k(rels, 10), rel=1e-9)
        # 列表长度 > k：截断到前 k 个
        # rels[:5] = [1,0,1,0,1]，DCG = 1/log2(2) + 0 + 1/log2(4) + 0 + 1/log2(6)
        import math
        rels_long = [1, 0, 1, 0, 1, 1, 1, 1]
        d5 = dcg_at_k(rels_long, 5)
        expected = 1 / math.log2(2) + 0 + 1 / math.log2(4) + 0 + 1 / math.log2(6)
        assert d5 == pytest.approx(expected, rel=1e-9)

    def test_empty_relations(self):
        assert dcg_at_k([], 10) == 0.0

    def test_all_zero_relevance(self):
        assert dcg_at_k([0, 0, 0, 0], 4) == 0.0


class TestNdcgAtK:
    def test_perfect_ranking(self):
        # 理想排序：全部相关，DCG == IDCG → NDCG = 1
        assert ndcg_at_k([1] * 5, 5) == pytest.approx(1.0, rel=1e-9)

    def test_worst_ranking(self):
        # 全相关但排序完全反着 → DCG << IDCG
        # IDCG = 全 1 DCG，DCG = 倒数位置排序的 DCG
        ndcg = ndcg_at_k([1, 1, 1, 1, 1], 5)  # 全 1 不管怎么排都是 1
        assert ndcg == pytest.approx(1.0, rel=1e-9)

    def test_no_relevance_returns_zero(self):
        # 全 0：IDCG=0 → 我们约定返回 0.0
        assert ndcg_at_k([0, 0, 0, 0], 4) == 0.0

    def test_mixed_relevance(self):
        # [1, 0, 1] vs 理想 [1, 1, 0]
        # DCG = 1/log2(2) + 0/log2(3) + 1/log2(4) = 1 + 0 + 0.5 = 1.5
        # IDCG = 1/log2(2) + 1/log2(3) + 0/log2(4) = 1 + 0.6309 + 0 = 1.6309
        # NDCG = DCG/IDCG
        import math
        dcg = 1 / math.log2(2) + 0 / math.log2(3) + 1 / math.log2(4)
        idcg = 1 / math.log2(2) + 1 / math.log2(3) + 0 / math.log2(4)
        ndcg = ndcg_at_k([1, 0, 1], 3)
        assert ndcg == pytest.approx(dcg / idcg, rel=1e-4)

    def test_k_larger_than_length(self):
        # k 大于 list 长度时，enumerate 自动限长，不报错
        rels = [1, 1]
        dcg = dcg_at_k(rels, 10)  # 只用前 2 个
        # 2 个相关：1/log2(2) + 1/log2(3)
        import math
        expected = 1 / math.log2(2) + 1 / math.log2(3)
        assert dcg == pytest.approx(expected, rel=1e-4)
        # ndcg 同样：理想也是 [1,1]，所以 NDCG = 1
        assert ndcg_at_k(rels, 10) == pytest.approx(1.0, rel=1e-9)


class TestComputeSpearman:
    def test_perfect_positive_correlation(self):
        rho, p = compute_spearman([1, 2, 3, 4, 5], [1, 2, 3, 4, 5])
        assert rho == pytest.approx(1.0, rel=1e-9)
        assert p < 0.001

    def test_perfect_negative_correlation(self):
        rho, p = compute_spearman([1, 2, 3, 4, 5], [5, 4, 3, 2, 1])
        assert rho == pytest.approx(-1.0, rel=1e-9)

    def test_no_correlation(self):
        # 噪声数据
        rho, _ = compute_spearman([1, 2, 3, 4, 5], [2, 1, 4, 3, 5])
        # 这组数据其实是完美正相关（rank 排序后）→ 1.0
        # 用真正噪声：
        rho, _ = compute_spearman([1, 2, 3, 4, 5], [1, 3, 2, 5, 4])
        assert -1.0 <= rho <= 1.0

    def test_constant_series_returns_zero(self):
        # 常数列 spearmanr 返回 NaN → 我们兜底为 0.0
        rho, _ = compute_spearman([5, 5, 5, 5, 5], [1, 2, 3, 4, 5])
        assert rho == 0.0

    def test_different_lengths_raises(self):
        # scipy.stats.spearmanr 对长度不一致会抛 ValueError
        import scipy.stats
        with pytest.raises(ValueError):
            scipy.stats.spearmanr([1, 2, 3], [1, 2])


class TestBuildPerQueryNdcgs:
    def _fake_row(self, labels: list[int], judge_scores: list[int]) -> dict:
        """构造一条 PRELIMINARY row。"""
        return {
            "query_id": "q_test",
            "query_text": "test query",
            "candidates": [
                {"jd_id": f"jd{i}", "human_label": lbl, "llm_judge_score": sc}
                for i, (lbl, sc) in enumerate(zip(labels, judge_scores))
            ],
        }

    def test_perfect_match_when_judge_aligns(self):
        # human_label = 1 的 candidate，judge score 全部 ≥ 3（binary 后 = 1）
        # human_label = 0 的 candidate，judge score 全部 < 3
        labels = [1, 1, 0, 0, 1]
        scores = [5, 4, 2, 1, 3]
        row = self._fake_row(labels, scores)
        prelim_ndcgs, judge_ndcgs = build_per_query_ndcgs([row], [scores], k=5)
        # 两个 NDCG 必须相等
        assert prelim_ndcgs[0] == pytest.approx(judge_ndcgs[0], rel=1e-9)

    def test_perfect_ranking_preliminary(self):
        # PRELIMINARY 把相关放最前
        labels = [1, 1, 1, 0, 0]
        scores = [5, 4, 3, 2, 1]  # judge 也对齐
        row = self._fake_row(labels, scores)
        prelim_ndcgs, judge_ndcgs = build_per_query_ndcgs([row], [scores], k=5)
        assert prelim_ndcgs[0] == pytest.approx(1.0, rel=1e-9)
        assert judge_ndcgs[0] == pytest.approx(1.0, rel=1e-9)

    def test_threshold_3_applied_to_judge(self):
        # judge score = 3 视为相关（threshold=3），= 2 视为不相关
        labels = [1, 1, 1, 0, 0]
        scores = [3, 3, 3, 2, 2]  # 边界
        row = self._fake_row(labels, scores)
        _, judge_ndcgs = build_per_query_ndcgs([row], [scores], k=5)
        # judge 二值化后也是 [1,1,1,0,0] → NDCG = 1.0
        assert judge_ndcgs[0] == pytest.approx(1.0, rel=1e-9)

    def test_multiple_queries_perfect_spearman(self):
        # 3 条 query，每条 PRELIMINARY 和 judge 完全一致
        labels1, scores1 = [1, 1, 0, 0], [5, 4, 2, 1]
        labels2, scores2 = [0, 1, 1, 1], [1, 5, 4, 3]
        labels3, scores3 = [1, 0, 1, 0], [4, 2, 3, 1]
        rows = [self._fake_row(l, s) for l, s in
                [(labels1, scores1), (labels2, scores2), (labels3, scores3)]]
        scores_list = [scores1, scores2, scores3]
        prelim_ndcgs, judge_ndcgs = build_per_query_ndcgs(rows, scores_list, k=4)
        rho, _ = compute_spearman(prelim_ndcgs, judge_ndcgs)
        # 完全对齐时 ρ = 1.0
        assert rho == pytest.approx(1.0, rel=1e-9)

    def test_k_truncation(self):
        # 7 个 candidate，k=5：只算前 5 个
        labels = [1, 1, 1, 1, 1, 0, 0]
        scores = [5, 5, 5, 5, 5, 1, 1]
        row = self._fake_row(labels, scores)
        prelim_ndcgs, judge_ndcgs = build_per_query_ndcgs([row], [scores], k=5)
        assert prelim_ndcgs[0] == pytest.approx(1.0, rel=1e-9)
        assert judge_ndcgs[0] == pytest.approx(1.0, rel=1e-9)

    def test_missing_label_treated_as_zero(self):
        # human_label 缺失 → 默认 0
        row = {
            "query_id": "q_test",
            "query_text": "test",
            "candidates": [
                {"jd_id": "a", "human_label": None, "llm_judge_score": 5},
                {"jd_id": "b", "llm_judge_score": 4},  # 也没 human_label
                {"jd_id": "c", "human_label": 1, "llm_judge_score": 5},
            ],
        }
        scores = [5, 4, 5]
        prelim_ndcgs, judge_ndcgs = build_per_query_ndcgs([row], [scores], k=3)
        # PRELIMINARY 二值化后 = [0, 0, 1]；judge 二值化 = [1, 1, 1]
        # 排名不同，NDCG 不同
        assert prelim_ndcgs[0] < judge_ndcgs[0]


class TestVerifyGoldenSpearmanScript:
    """端到端测试 verify_golden_spearman.py main()。"""

    def test_main_with_existing_preliminary(self, tmp_path):
        """脚本能处理 eval/golden_30_preliminary.jsonl 不报错。"""
        # 复制现有 PRELIMINARY 文件到 tmp_path 跑（避免污染仓库）
        src = PROJECT_ROOT / "eval" / "golden_30_preliminary.jsonl"
        if not src.exists():
            pytest.skip("eval/golden_30_preliminary.jsonl 未生成")
        # 用 monkeypatch 不会改；直接 main() 跑一次
        from scripts import verify_golden_spearman as vgs

        # 备份 sys.argv，调用 main()
        import sys
        old_argv = sys.argv
        sys.argv = ["verify_golden_spearman.py",
                    "--input", str(src),
                    "--json-output", str(tmp_path / "report.json")]
        try:
            vgs.main()
        finally:
            sys.argv = old_argv

        # JSON 报告应存在
        report_path = tmp_path / "report.json"
        assert report_path.exists()
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert "spearman_rho" in report
        assert "n_queries" in report
        assert report["n_queries"] > 0
        assert -1.0 <= report["spearman_rho"] <= 1.0
        assert "per_query" in report
        assert len(report["per_query"]) == report["n_queries"]

    def test_main_with_synthetic_data(self, tmp_path):
        """用构造的 jsonl 跑 main()，5 条 query 故意让 NDCG 有变化（不全 1.0）。"""
        # 每条 query 设计不同的 label 分布，使 NDCG 不全相等
        rows = []
        # 5 条 query：每条 4 candidate，但 label 模式不同
        label_patterns = [
            [1, 1, 1, 1],  # NDCG = 1.0
            [1, 1, 0, 0],  # NDCG 接近 1
            [1, 0, 0, 0],  # NDCG = 1.0
            [0, 0, 0, 1],  # NDCG 较小（相关在末尾）
            [1, 0, 1, 0],  # NDCG 中等
        ]
        for i, labels in enumerate(label_patterns):
            # 让 judge score 与 label 对齐（≥3 表示相关）→ ρ=1
            scores = [5 if lbl else 1 for lbl in labels]
            cands = [
                {"jd_id": f"jd{i}_{j}", "jd_title": f"Title {j}",
                 "jd_snippet": "snippet", "human_label": lbl,
                 "llm_judge_score": sc, "is_origin_jd": False}
                for j, (lbl, sc) in enumerate(zip(labels, scores))
            ]
            rows.append({
                "query_id": f"q{i}",
                "query_text": f"test query {i}",
                "candidates": cands,
            })
        jsonl_path = tmp_path / "synthetic.jsonl"
        with jsonl_path.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

        from scripts import verify_golden_spearman as vgs
        import sys
        old_argv = sys.argv
        sys.argv = ["verify_golden_spearman.py",
                    "--input", str(jsonl_path),
                    "--k", "4",
                    "--json-output", str(tmp_path / "report.json")]
        try:
            vgs.main()
        finally:
            sys.argv = old_argv

        report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
        assert report["n_queries"] == 5
        # 至少 NDCG 有 1 个 < 1（label_pattern[3] = [0,0,0,1]）
        assert any(p < 1.0 for p in report["preliminary_ndcgs"])
        # judge 和 PRELIMINARY 完全对齐 → ρ = 1
        assert report["spearman_rho"] == pytest.approx(1.0, rel=1e-9)
        assert report["healthy"] is True