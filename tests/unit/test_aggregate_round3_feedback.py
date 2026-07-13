# -*- coding: utf-8 -*-
"""round-3 反馈汇总脚本单测

按 docs/round3_user_trial.md §7：验证 aggregate_round3_feedback.py 能：
- 加载 JSONL
- 聚合 N 条用户反馈
- 渲染 Markdown 报告（验证必要字段都在）
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


SAMPLE_FEEDBACK = [
    {
        "user_id": "u01", "submitted_at": "2026-07-13T10:00:00",
        "q1_step_reached": "Step 5", "q2_time_minutes": 15,
        "q3_blocked_steps": ["Step 2: 默认 1 段教育 + 1 段工作太少了"],
        "q4_quality": {"preserve_numbers": 5, "natural_rewrite": 4,
                       "no_fabrication": 5, "rewrite_reason_helpful": 4},
        "q5_use_intent": "微调后用", "q5_what_to_fix": ["加项目字段默认 1 段"],
        "q6_surprise": "模式 A 改写后数字保留很准",
        "q7_cut": "Step 4 进度条可省略",
        "q8_next": "加一键投递 Boss/猎聘",
    },
    {
        "user_id": "u02", "submitted_at": "2026-07-13T11:00:00",
        "q1_step_reached": "Step 3", "q2_time_minutes": 25,
        "q3_blocked_steps": ["Step 3: 模式 B 编造了'字节跳动'"],
        "q4_quality": {"preserve_numbers": 3, "natural_rewrite": 5,
                       "no_fabrication": 2, "rewrite_reason_helpful": 3},
        "q5_use_intent": "重写一份",
        "q6_surprise": "模式 B 模板生成很快",
        "q7_cut": "Step 2 表单太长了",
        "q8_next": "支持多语言简历",
    },
    {
        "user_id": "u03", "submitted_at": "2026-07-13T12:00:00",
        "q1_step_reached": "Step 5", "q2_time_minutes": 12,
        "q3_blocked_steps": [],
        "q4_quality": {"preserve_numbers": 5, "natural_rewrite": 5,
                       "no_fabrication": 5, "rewrite_reason_helpful": 5},
        "q5_use_intent": "直接用",
        "q6_surprise": "一页纸预览进度条很直观",
        "q7_cut": "无",
        "q8_next": "支持 PDF 水印",
    },
]


@pytest.fixture
def tmp_jsonl(tmp_path):
    p = tmp_path / "feedback.jsonl"
    with p.open("w", encoding="utf-8") as f:
        for row in SAMPLE_FEEDBACK:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return p


@pytest.fixture
def tmp_report(tmp_path):
    return tmp_path / "report.md"


class TestAggregateRound3Feedback:
    def test_load_feedback(self, tmp_jsonl):
        """JSONL 加载：3 条样本正确解析。"""
        from scripts.aggregate_round3_feedback import load_feedback
        rows = load_feedback(tmp_jsonl)
        assert len(rows) == 3
        assert rows[0]["user_id"] == "u01"
        assert rows[2]["q5_use_intent"] == "直接用"

    def test_aggregate_basic_stats(self, tmp_jsonl):
        """基础统计：完成率 / 平均耗时 / 步骤分布。"""
        from scripts.aggregate_round3_feedback import load_feedback, aggregate
        rows = load_feedback(tmp_jsonl)
        stats = aggregate(rows)

        assert stats["n"] == 3
        assert stats["full_run"] == 2  # u01 + u03 跑完 Step 5
        assert stats["full_run_rate"] == "2/3 = 67%"
        assert stats["avg_time_minutes"] == pytest.approx((15 + 25 + 12) / 3, abs=0.1)
        assert stats["step_counter"]["Step 5"] == 2
        assert stats["step_counter"]["Step 3"] == 1

    def test_aggregate_q4_quality(self, tmp_jsonl):
        """q4 AI 改写质量 4 维度平均分。"""
        from scripts.aggregate_round3_feedback import load_feedback, aggregate
        stats = aggregate(load_feedback(tmp_jsonl))

        # preserve_numbers: (5+3+5)/3 = 4.33
        assert stats["q4_avg"]["preserve_numbers"] == pytest.approx(4.33, abs=0.01)
        # no_fabrication: (5+2+5)/3 = 4.0
        assert stats["q4_avg"]["no_fabrication"] == pytest.approx(4.0, abs=0.01)

    def test_aggregate_blocked_steps(self, tmp_jsonl):
        """q3 卡点聚合。"""
        from scripts.aggregate_round3_feedback import load_feedback, aggregate
        stats = aggregate(load_feedback(tmp_jsonl))

        assert "Step 2" in stats["blocked_counter"]
        assert "Step 3" in stats["blocked_counter"]
        assert stats["blocked_counter"]["Step 2"] == 1
        assert stats["blocked_counter"]["Step 3"] == 1

    def test_aggregate_intent_distribution(self, tmp_jsonl):
        """q5 用户取舍分布。"""
        from scripts.aggregate_round3_feedback import load_feedback, aggregate
        stats = aggregate(load_feedback(tmp_jsonl))

        assert stats["intent_counter"]["直接用"] == 1
        assert stats["intent_counter"]["微调后用"] == 1
        assert stats["intent_counter"]["重写一份"] == 1

    def test_render_report_contains_required_sections(self, tmp_jsonl, tmp_report):
        """报告渲染：含 §1-§10 所有必要小节。"""
        from scripts.aggregate_round3_feedback import load_feedback, aggregate, render_report
        rows = load_feedback(tmp_jsonl)
        stats = aggregate(rows)
        render_report(stats, tmp_report)

        content = tmp_report.read_text(encoding="utf-8")
        assert "## 1. 用户样本" in content
        assert "## 2. 完成率" in content
        assert "## 3. AI 改写质量" in content
        assert "## 4. 用户取舍" in content
        assert "## 5. 痛点 TOP-N" in content
        assert "## 6. 惊喜 TOP-N" in content
        assert "## 7. 想砍掉的 TOP-N" in content
        assert "## 8. 下个版本最想要" in content
        assert "## 9. §6 验收 checklist 收口" in content
        assert "## 10. 下一轮建议" in content
        # 数据正确
        assert "N = 3" in content
        assert "2/3 = 67%" in content

    def test_render_empty_input(self, tmp_path):
        """空输入时不报错，给出友好提示。"""
        from scripts.aggregate_round3_feedback import aggregate, render_report

        empty_jsonl = tmp_path / "empty.jsonl"
        empty_jsonl.write_text("", encoding="utf-8")
        from scripts.aggregate_round3_feedback import load_feedback
        rows = load_feedback(empty_jsonl)
        stats = aggregate(rows)

        report = tmp_path / "report.md"
        render_report(stats, report)
        assert "没有用户反馈数据" in report.read_text(encoding="utf-8")

    def test_cli_end_to_end(self, tmp_jsonl, tmp_report):
        """命令行入口端到端：--input --output 都正确。"""
        result = subprocess.run(
            [sys.executable, "scripts/aggregate_round3_feedback.py",
             "--input", str(tmp_jsonl), "--output", str(tmp_report)],
            capture_output=True, cwd=Path(__file__).resolve().parent.parent.parent,
            env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
        )
        assert result.returncode == 0, f"CLI 失败：{result.stderr.decode('utf-8', errors='replace')}"
        assert tmp_report.exists()
        assert "N = 3" in tmp_report.read_text(encoding="utf-8")

    def test_missing_file_exits_with_clear_message(self, tmp_path):
        """JSONL 不存在时给清晰错误并 exit 1。"""
        import os
        result = subprocess.run(
            [sys.executable, "scripts/aggregate_round3_feedback.py",
             "--input", str(tmp_path / "nonexistent.jsonl"),
             "--output", str(tmp_path / "report.md")],
            capture_output=True, cwd=Path(__file__).resolve().parent.parent.parent,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        assert result.returncode == 1
        stderr_text = result.stderr.decode("utf-8", errors="replace")
        assert "不存在" in stderr_text