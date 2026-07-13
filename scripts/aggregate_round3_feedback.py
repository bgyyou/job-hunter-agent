# -*- coding: utf-8 -*-
"""round-3 真实用户反馈汇总脚本

按 docs/round3_user_trial.md §7：读 `data/round3_feedback.jsonl` →
生成 `docs/round3_closing_report.md`（§4 模板填好版）。

用法：
    python scripts/aggregate_round3_feedback.py
    python scripts/aggregate_round3_feedback.py --input data/other.jsonl --output docs/other.md
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = PROJECT_ROOT / "data" / "round3_feedback.jsonl"
DEFAULT_OUTPUT = PROJECT_ROOT / "docs" / "round3_closing_report.md"


def load_feedback(input_path: Path) -> List[Dict[str, Any]]:
    """加载 JSONL 反馈（每行一条）。"""
    if not input_path.exists():
        print(f"❌ 反馈文件不存在：{input_path}", file=sys.stderr)
        print(f"   请先用 docs/round3_user_trial.md §3 schema 收集用户反馈。", file=sys.stderr)
        sys.exit(1)
    rows = []
    with input_path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"⚠️  第 {lineno} 行 JSON 解析失败：{e}", file=sys.stderr)
    return rows


def aggregate(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """汇总 N 条反馈。"""
    n = len(rows)
    if n == 0:
        return {"n": 0}

    # 跑到的步骤分布
    step_counter = Counter(r.get("q1_step_reached", "未知") for r in rows)
    full_run = sum(1 for r in rows if r.get("q1_step_reached") == "Step 5")

    # 耗时分布
    times = [r.get("q2_time_minutes", 0) for r in rows if isinstance(r.get("q2_time_minutes"), int)]
    avg_time = statistics.mean(times) if times else 0

    # 卡在哪一步
    blocked_counter = Counter()
    for r in rows:
        for step in r.get("q3_blocked_steps", []):
            # 提取 step 名（如 "Step 2: xxx" → "Step 2"）
            step_name = step.split(":")[0].strip() if ":" in step else step
            blocked_counter[step_name] += 1

    # AI 改写质量（4 维度平均分）
    q4_keys = ["preserve_numbers", "natural_rewrite", "no_fabrication", "rewrite_reason_helpful"]
    q4_avg = {}
    q4_std = {}
    for k in q4_keys:
        vals = [r["q4_quality"][k] for r in rows
                if r.get("q4_quality") and isinstance(r["q4_quality"].get(k), (int, float))]
        q4_avg[k] = round(statistics.mean(vals), 2) if vals else 0
        q4_std[k] = round(statistics.stdev(vals), 2) if len(vals) >= 2 else 0

    # 用户取舍
    intent_counter = Counter(r.get("q5_use_intent", "未知") for r in rows)

    # 痛点 / 惊喜 / 砍掉 / 下版本
    pain_points = [item for r in rows for item in r.get("q3_blocked_steps", [])]
    surprises = [r.get("q6_surprise", "").strip() for r in rows if r.get("q6_surprise", "").strip()]
    cuts = [r.get("q7_cut", "").strip() for r in rows if r.get("q7_cut", "").strip()]
    nexts = [r.get("q8_next", "").strip() for r in rows if r.get("q8_next", "").strip()]

    return {
        "n": n,
        "step_counter": dict(step_counter),
        "full_run": full_run,
        "full_run_rate": f"{full_run}/{n} = {full_run / n * 100:.0f}%",
        "avg_time_minutes": round(avg_time, 1),
        "blocked_counter": dict(blocked_counter),
        "q4_avg": q4_avg,
        "q4_std": q4_std,
        "intent_counter": dict(intent_counter),
        "pain_points": pain_points,
        "surprises": surprises,
        "cuts": cuts,
        "nexts": nexts,
    }


def render_report(stats: Dict[str, Any], output_path: Path) -> None:
    """按 docs/round3_user_trial.md §4 模板渲染 Markdown 报告。"""
    n = stats["n"]
    if n == 0:
        output_path.write_text("# round-3 收口报告\n\n⚠️ 没有用户反馈数据。请先收集。\n", encoding="utf-8")
        return

    lines = [
        "# round-3 收口报告",
        "",
        f"> 自动生成 by `scripts/aggregate_round3_feedback.py`",
        f"> 输入：`data/round3_feedback.jsonl`（{n} 条用户反馈）",
        "",
        "## 1. 用户样本",
        f"- **N = {n}**（目标 ≥ 3）",
        "",
        "## 2. 完成率",
        f"- 跑完全流程（Step 5）：**{stats['full_run']}**/N = {stats['full_run_rate']}",
        f"- 平均耗时：**{stats['avg_time_minutes']} 分钟**",
        "",
        "### 各步骤到达人数",
        "| 步骤 | 人数 |",
        "|---|---|",
    ]
    for step, count in sorted(stats["step_counter"].items(), key=lambda x: -x[1]):
        lines.append(f"| {step} | {count} |")

    lines += [
        "",
        "### 卡在哪一步（q3 多选）",
        "| 卡点 | 次数 |",
        "|---|---|",
    ]
    if stats["blocked_counter"]:
        for step, count in sorted(stats["blocked_counter"].items(), key=lambda x: -x[1]):
            lines.append(f"| {step} | {count} |")
    else:
        lines.append("| （无） | – |")

    lines += [
        "",
        "## 3. AI 改写质量（q4 平均分 / 5）",
        "| 维度 | 平均分 | 标准差 |",
        "|---|---|---|",
    ]
    q4_labels = {
        "preserve_numbers": "保留原数字 / 公司名",
        "natural_rewrite": "改写自然（不像机器人）",
        "no_fabrication": "模式 B 不编造具体公司/学校",
        "rewrite_reason_helpful": "改写说明有帮",
    }
    for k, label in q4_labels.items():
        lines.append(f"| {label} | {stats['q4_avg'][k]} | {stats['q4_std'][k]} |")

    lines += [
        "",
        "## 4. 用户取舍（q5）",
        "| 意愿 | 人数 |",
        "|---|---|",
    ]
    for intent, count in sorted(stats["intent_counter"].items(), key=lambda x: -x[1]):
        lines.append(f"| {intent} | {count} |")

    lines += [
        "",
        "## 5. 痛点 TOP-N（q3 提及频次）",
    ]
    if stats["pain_points"]:
        for i, p in enumerate(stats["pain_points"][:10], 1):
            lines.append(f"{i}. {p}")
    else:
        lines.append("（无）")

    lines += [
        "",
        "## 6. 惊喜 TOP-N（q6 提及频次）",
    ]
    if stats["surprises"]:
        for i, s in enumerate(stats["surprises"][:10], 1):
            lines.append(f"{i}. {s}")
    else:
        lines.append("（无）")

    lines += [
        "",
        "## 7. 想砍掉的 TOP-N（q7 提及频次）",
    ]
    if stats["cuts"]:
        for i, c in enumerate(stats["cuts"][:10], 1):
            lines.append(f"{i}. {c}")
    else:
        lines.append("（无）")

    lines += [
        "",
        "## 8. 下个版本最想要 TOP-N（q8 提及频次）",
    ]
    if stats["nexts"]:
        for i, nxt in enumerate(stats["nexts"][:10], 1):
            lines.append(f"{i}. {nxt}")
    else:
        lines.append("（无）")

    lines += [
        "",
        "## 9. §6 验收 checklist 收口",
        f"- [{'x' if n >= 3 else ' '}] 至少 3 个真实用户跑通全流程（实测 {n}）",
        f"- [{'x' if n >= 5 else ' '}] 至少 5 个真实用户跑通全流程（实测 {n}）",
        f"- [{'x' if stats['full_run'] >= 1 else ' '}] P0-1 PDF fallback：至少 1 人成功导出",
        f"- [{'x' if stats['full_run'] >= 1 else ' '}] P0-2 真 LLM 跑通：至少 1 人成功生成简历",
        "",
        "## 10. 下一轮建议（人工 review 后填）",
        "",
        "（基于上面痛点 / 想砍 / 下版本想要的综合判断，写 round-4 计划或直接 v3.0 release 决策）",
        "",
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"✅ 报告已生成：{output_path}")
    print(f"   {n} 条用户反馈 → {len(lines)} 行 Markdown")


def main():
    parser = argparse.ArgumentParser(description="round-3 真实用户反馈汇总")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT,
                        help=f"反馈 JSONL 路径（默认 {DEFAULT_INPUT}）")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help=f"报告输出路径（默认 {DEFAULT_OUTPUT}）")
    args = parser.parse_args()

    rows = load_feedback(args.input)
    stats = aggregate(rows)
    render_report(stats, args.output)


if __name__ == "__main__":
    main()