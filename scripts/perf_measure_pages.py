"""五关键页面首次响应时间测量（R9-P1 埋点入口）

历史：R13b-prep（2026-08-04）落地 R9-P1 测量方式。owner 跑本脚本回填数字到
REVIEW.md 的 R9-P1 行。基线 695 测试依赖 streamlit.testing.v1.AppTest
（见 tests/unit/test_apptest_smoke.py）。

用法：
    python scripts/perf_measure_pages.py            # 跑全部 5 个页面
    python scripts/perf_measure_pages.py --timeout 60  # 调超时

输出（stdout, UTF-8）：
    03_📝_Flow_A_Step1.py: 1.23s
    04_📝_Flow_A_Step2.py: 0.98s
    06_📄_Flow_B.py: 1.45s
    07_📚_JD_Library.py: 1.12s
    08_📈_Application_History.py: 0.87s

    平均: 1.13s (目标 ≤ 3.0s)

任何页面加载失败会把异常写入 stderr 并跳过该页面，最终统计基于成功页面。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Windows GBK console 兼容：emoji 文件名需要 UTF-8 输出
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

REPO_ROOT = Path(__file__).resolve().parents[1]

PAGES = [
    "pages/03_📝_Flow_A_Step1.py",
    "pages/04_📝_Flow_A_Step2.py",
    "pages/06_📄_Flow_B.py",
    "pages/07_📚_JD_Library.py",
    "pages/08_📈_Application_History.py",
]

TARGET_AVG_SECONDS = 3.0


def measure_page(page_path: Path, timeout: int) -> float:
    """用 AppTest 加载页面并测量首次 run 的耗时（秒）。"""
    from streamlit.testing.v1 import AppTest

    start = time.perf_counter()
    at = AppTest.from_file(str(page_path), default_timeout=timeout).run(timeout=timeout)
    elapsed = time.perf_counter() - start
    if at.exception:
        first = at.exception[0]
        raise RuntimeError(f"{page_path.name}: {type(first).__name__}: {first.value}")
    return elapsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="单个页面 run 的超时秒数（默认 30）",
    )
    parser.add_argument(
        "--target",
        type=float,
        default=TARGET_AVG_SECONDS,
        help=f"平均耗时目标秒数（默认 {TARGET_AVG_SECONDS}）",
    )
    args = parser.parse_args()

    results: dict[str, float] = {}
    for rel in PAGES:
        page = REPO_ROOT / rel
        if not page.exists():
            print(f"{page.name}: SKIP (file not found)", file=sys.stderr)
            continue
        try:
            secs = measure_page(page, timeout=args.timeout)
            results[page.name] = secs
            print(f"{page.name}: {secs:.2f}s")
        except Exception as exc:  # noqa: BLE001
            print(f"{page.name}: ERROR {exc}", file=sys.stderr)

    if not results:
        print("ERROR: no pages measured successfully", file=sys.stderr)
        return 1

    avg = sum(results.values()) / len(results)
    print(f"\n平均: {avg:.2f}s (目标 ≤ {args.target:.1f}s, n={len(results)}/{len(PAGES)})")
    return 0 if avg <= args.target else 2


if __name__ == "__main__":
    raise SystemExit(main())