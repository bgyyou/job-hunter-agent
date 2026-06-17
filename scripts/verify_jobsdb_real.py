"""手动测一条真实 JobsDB URL（M2.5 验证补充）"""
import asyncio
import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from tools.llm import VolcanoClient  # noqa: E402
from tools.scraper.jd_analyzer_enhanced import JDAnalyzerEnhanced  # noqa: E402


RAW_URL = "https://hk.jobsdb.com/job/92779383/apply?sol=d1c23669e78ba8b87a1decfce80a66ab8ea5d44d#view-job"


def normalize_jobsdb_url(raw: str) -> str:
    """Strip /apply 后缀和 query / fragment，回到 view-job 详情 URL"""
    m = re.match(r"(https://hk\.jobsdb\.com/job/\d+)", raw)
    return m.group(1) if m else raw


async def main():
    url = normalize_jobsdb_url(RAW_URL)
    print(f"[INFO] 原始 URL  : {RAW_URL}")
    print(f"[INFO] 规范化 URL: {url}")
    print("[INFO] 即将弹出 Edge 浏览器；若卡在 Cloudflare 验证页，请在 30 秒内手动通过\n")

    llm = VolcanoClient(
        api_key=os.environ["VOLCANO_API_KEY"],
        api_url=os.getenv("VOLCANO_CODING_API_URL", "https://apihub.agnes-ai.com/v1").rstrip("/"),
        model=os.getenv("VOLCANO_MODEL", "agnes-2.0-flash"),
    )
    analyzer = JDAnalyzerEnhanced(llm_client=llm)

    try:
        result = await analyzer.parse_from_url(url)
    except Exception as e:
        print(f"\n[FAIL] 抓取失败: {type(e).__name__}: {e}")
        return

    print("\n[OK] 抓取并分析成功")
    print("-" * 60)
    print(f"  title              : {result.get('title')!r}")
    print(f"  company            : {result.get('company')!r}")
    print(f"  location           : {result.get('location')!r}")
    print(f"  salary_range       : {result.get('salary_range')!r}")
    print(f"  language           : {result.get('language')!r}")
    print(f"  raw_text len       : {len(result.get('raw_text') or '')} chars")
    print(f"  core_requirements  : {len(result.get('core_requirements') or [])} items")
    for i, r in enumerate((result.get("core_requirements") or [])[:5]):
        print(f"    [{i}] {r}")
    print(f"  preferred_req      : {len(result.get('preferred_requirements') or [])} items")
    print(f"  keywords           : {result.get('keywords')[:10] if result.get('keywords') else []}")
    impl = result.get("implicit_requirements") or ""
    if isinstance(impl, list):
        impl = " | ".join(impl)
    print(f"  implicit_req       : {impl[:120]!r}{'...' if len(impl) > 120 else ''}")

    out = PROJECT_ROOT / "data" / "temp" / "m2_5_jobsdb_real_dump.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  完整结果落盘: {out.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    asyncio.run(main())
