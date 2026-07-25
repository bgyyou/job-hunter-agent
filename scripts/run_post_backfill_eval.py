"""Backfill 完后一键跑评测的脚本 (P0-模块 6 子任务 1 后置 / 模块 4 验收)

流程：
1. 检测 DB 中 knowledge_chunks.translated_at 完成度（已翻译 / 总数）
2. 如未达到阈值（默认 99%），警告但允许强跑
3. 跑 eval/run_eval.py 的 baseline 评测（50 query，concurrency=2）
4. 对比新旧基线数字（NDCG@10 / Recall@10 / MRR / Hit Rate / n_zero）
5. 写 data/post_backfill_eval_<ts>.json 完整结果
6. 写 data/post_backfill_eval_<ts>.md 人类可读对比报告（含 CHANGELOG snippet）
7. 把 CHANGELOG snippet append 到 CHANGELOG.md（draft 段，不直接 commit）

用法：
    # 默认检测 backfill 进度（>=99% 才跑）
    python scripts/run_post_backfill_eval.py

    # 强制跑（不管 backfill 完成度）
    python scripts/run_post_backfill_eval.py --force

    # 自定义阈值
    python scripts/run_post_backfill_eval.py --threshold 0.95
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from eval.run_eval import load_queries, run, write_outputs  # noqa: E402


def check_backfill_progress(db_path: Path) -> dict:
    """查 DB 中 knowledge_chunks 的翻译进度。"""
    conn = sqlite3.connect(str(db_path))
    total = conn.execute(
        "SELECT COUNT(*) FROM knowledge_chunks WHERE deleted_at IS NULL"
    ).fetchone()[0]
    done = conn.execute(
        "SELECT COUNT(*) FROM knowledge_chunks "
        "WHERE deleted_at IS NULL AND translated_at IS NOT NULL"
    ).fetchone()[0]
    pending = conn.execute(
        "SELECT COUNT(*) FROM knowledge_chunks "
        "WHERE deleted_at IS NULL "
        "AND (translated_at IS NULL OR chunk_text = original_text) "
        "AND original_text IS NOT NULL"
    ).fetchone()[0]
    conn.close()
    ratio = done / total if total else 0.0
    return {
        "total": total,
        "done": done,
        "pending": pending,
        "ratio": ratio,
    }


def load_latest_baseline(data_dir: Path) -> dict:
    """加载最新一份 baseline JSON（与本次对比的旧数字）。"""
    files = sorted(data_dir.glob("eval_baseline_*.json"))
    if not files:
        return {}
    latest = files[-1]
    return json.loads(latest.read_text(encoding="utf-8"))


def build_report(
    new_summary: dict,
    old_baseline: dict,
    progress: dict,
    ts: str,
) -> str:
    """生成 markdown 对比报告 + CHANGELOG snippet。"""
    lines = []
    lines.append(f"# Backfill 后 RAG 评测 ({ts})")
    lines.append("")
    lines.append("## 0. Backfill 进度")
    lines.append(f"- 已翻译: **{progress['done']}/{progress['total']}** "
                 f"({progress['ratio'] * 100:.1f}%)")
    lines.append(f"- 待翻译: {progress['pending']}")
    lines.append("")
    lines.append("## 1. 新 baseline 数字")
    lines.append(f"- judge_model: `{new_summary['judge_model']}`")
    lines.append(f"- judge_strategy: `{new_summary['judge_strategy']}`")
    lines.append(f"- judge mock queries: **{new_summary['judge_mock_fallbacks']}/{new_summary['judge_api_calls']}** "
                 f"({(new_summary['judge_mock_fallbacks'] / max(new_summary['judge_api_calls'], 1) * 100):.1f}%)")
    lines.append(f"- NDCG@10: **{new_summary['ndcg_at_10']:.4f}**")
    lines.append(f"- Recall@10: **{new_summary['recall_at_10']:.4f}**")
    lines.append(f"- MRR: **{new_summary['mrr']:.4f}**")
    lines.append(f"- Hit Rate: **{new_summary['hit_rate']:.4f}**")
    lines.append(f"- n_zero_relevant_in_top10: **{new_summary['n_zero_relevant_in_top10']}**/{new_summary['num_queries']}")
    lines.append("")
    lines.append("## 2. 对比旧 baseline")
    if not old_baseline:
        lines.append("- 无旧 baseline 对比（首次跑）")
    else:
        lines.append("")
        lines.append("| 指标 | 旧 (rerank ON) | 新 (translation) | Δ 绝对 | Δ 相对 | 解读 |")
        lines.append("|---|---|---|---|---|---|")
        rows = [
            ("NDCG@10", "ndcg_at_10", True),
            ("Recall@10", "recall_at_10", True),
            ("MRR", "mrr", True),
            ("Hit Rate", "hit_rate", True),
        ]
        for label, key, higher_better in rows:
            old_v = old_baseline.get(key, 0)
            new_v = new_summary.get(key, 0)
            d_abs = new_v - old_v
            d_rel = (d_abs / old_v * 100) if old_v else 0
            sign = "+" if d_abs >= 0 else ""
            arrow = "↑" if d_abs > 0 else ("↓" if d_abs < 0 else "→")
            verdict = "↑ 涨" if d_abs > 0.005 else ("↓ 跌" if d_abs < -0.005 else "→ 持平")
            lines.append(
                f"| {label} | {old_v:.4f} | {new_v:.4f} | "
                f"{sign}{d_abs:.4f} | {sign}{d_rel:.1f}% | {verdict} {arrow} |"
            )

        old_zero = old_baseline.get("n_zero_relevant_in_top10", 0)
        new_zero = new_summary.get("n_zero_relevant_in_top10", 0)
        d_zero = new_zero - old_zero
        sign = "+" if d_zero > 0 else ""
        verdict = "↓ 跌（变好）" if d_zero < 0 else ("↑ 涨（变差）" if d_zero > 0 else "→ 持平")
        lines.append(
            f"| n_zero_relevant_in_top10 | {old_zero} | {new_zero} | "
            f"{sign}{d_zero} | — | {verdict} |"
        )
    lines.append("")
    lines.append("## 3. CHANGELOG snippet（草稿，不直接 commit）")
    lines.append("")
    lines.append("```markdown")
    lines.append(f"### [{ts}] Cross-language RAG 翻译 backfill 验收")
    lines.append("")
    lines.append("- **Backfill 进度**: " + f"{progress['done']}/{progress['total']} "
                 f"({progress['ratio'] * 100:.1f}%)")
    if old_baseline:
        lines.append(f"- **NDCG@10**: {old_baseline.get('ndcg_at_10', 0):.4f} → "
                     f"{new_summary['ndcg_at_10']:.4f}")
        lines.append(f"- **Recall@10**: {old_baseline.get('recall_at_10', 0):.4f} → "
                     f"{new_summary['recall_at_10']:.4f}")
        lines.append(f"- **MRR**: {old_baseline.get('mrr', 0):.4f} → "
                     f"{new_summary['mrr']:.4f}")
        lines.append(f"- **n_zero_relevant_in_top10**: "
                     f"{old_baseline.get('n_zero_relevant_in_top10', 0)} → "
                     f"{new_summary['n_zero_relevant_in_top10']}")
    lines.append("- **判定**: TODO（涨/跌/持平 + 结论）")
    lines.append("- **后续**: TODO（继续 rerank / query 改写 / chunk 切分）")
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--queries",
        default="eval/baseline_50_queries.jsonl",
        help="评测 query 文件（默认 50 query baseline 集，保证可比）",
    )
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument(
        "--threshold", type=float, default=0.99,
        help="backfill 完成度门槛（默认 99%）",
    )
    parser.add_argument("--force", action="store_true", help="无视 backfill 完成度强制跑")
    parser.add_argument("--no-judge", action="store_true")
    args = parser.parse_args()

    db_path = PROJECT_ROOT / "data" / "jobhunter_v2.db"
    data_dir = PROJECT_ROOT / "data"

    print(f"[STEP 1] 检测 backfill 进度：{db_path}")
    progress = check_backfill_progress(db_path)
    print(f"  total={progress['total']} done={progress['done']} "
          f"ratio={progress['ratio'] * 100:.1f}%")
    if progress['ratio'] < args.threshold and not args.force:
        print(f"[ABORT] backfill 完成度 {progress['ratio'] * 100:.1f}% < "
              f"{args.threshold * 100:.0f}%。等 backfill 跑完再试，或加 --force。")
        sys.exit(1)
    if progress['ratio'] < args.threshold:
        print(f"[WARN] backfill 完成度 {progress['ratio'] * 100:.1f}% < "
              f"{args.threshold * 100:.0f}%，但 --force 触发继续跑")

    print(f"[STEP 2] 加载旧 baseline 用于对比")
    old_baseline = load_latest_baseline(data_dir)
    if old_baseline:
        print(f"  旧 baseline: NDCG@10={old_baseline.get('ndcg_at_10'):.4f} "
              f"Recall@10={old_baseline.get('recall_at_10'):.4f} "
              f"MRR={old_baseline.get('mrr'):.4f} "
              f"n_zero={old_baseline.get('n_zero_relevant_in_top10')}")
    else:
        print(f"  无旧 baseline（首次跑）")

    print(f"[STEP 3] 加载 query + 跑评测")
    queries = load_queries(PROJECT_ROOT / args.queries)
    print(f"  queries: {len(queries)} 条")

    summary = asyncio.run(run(
        queries=queries,
        top_k=args.top_k,
        concurrency=args.concurrency,
        use_judge=not args.no_judge,
    ))

    print(f"[STEP 4] 写入 baseline JSON + 更新 rag_progress.json")
    write_outputs(summary, PROJECT_ROOT / args.queries, out_dir=data_dir)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    print(f"[STEP 5] 生成对比报告")
    report = build_report(summary, old_baseline, progress, ts)
    report_path = data_dir / f"post_backfill_eval_{ts}.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"  报告写入: {report_path}")

    print()
    print("=" * 60)
    print(f"NDCG@10:    {summary['ndcg_at_10']:.4f}  "
          f"(旧 {old_baseline.get('ndcg_at_10', 0):.4f})")
    print(f"Recall@10:  {summary['recall_at_10']:.4f}  "
          f"(旧 {old_baseline.get('recall_at_10', 0):.4f})")
    print(f"MRR:        {summary['mrr']:.4f}  "
          f"(旧 {old_baseline.get('mrr', 0):.4f})")
    print(f"Hit Rate:   {summary['hit_rate']:.4f}  "
          f"(旧 {old_baseline.get('hit_rate', 0):.4f})")
    print(f"n_zero:     {summary['n_zero_relevant_in_top10']}/{summary['num_queries']}  "
          f"(旧 {old_baseline.get('n_zero_relevant_in_top10', 0)})")
    print("=" * 60)


if __name__ == "__main__":
    main()