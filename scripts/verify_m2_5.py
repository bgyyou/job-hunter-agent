"""M2.5 自动化验证脚本（v2.1 M2.5.3 配套）

跑两组测试：
1. 简历解析 LLM 路径 vs 正则路径，对比抽取完整度
2. URL JD 路径失败时是否正确 raise（而非 silent return ""）

无浏览器 UI 依赖，纯 Python 调用。
"""
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

from tools.llm import VolcanoClient  # noqa: E402
from tools.resume_parser import ResumeParser  # noqa: E402
from tools.scraper.jd_analyzer_enhanced import JDAnalyzerEnhanced  # noqa: E402


SAMPLE_PDF = PROJECT_ROOT / "data" / "temp" / "Zheng Haowen CV(AI PM) .pdf"


def make_llm():
    return VolcanoClient(
        api_key=os.environ["VOLCANO_API_KEY"],
        api_url=os.getenv("VOLCANO_CODING_API_URL", "https://apihub.agnes-ai.com/v1").rstrip("/"),
        model=os.getenv("VOLCANO_MODEL", "agnes-2.0-flash"),
    )


def summarize(label: str, result: dict):
    header = result.get("header", {})
    contact = header.get("contact", {})
    exp = result.get("experience", [])
    proj = result.get("projects", [])
    skills = result.get("skills", {})
    edu = result.get("education", [])

    print(f"\n=== {label} ===")
    print(f"  name        : {header.get('name')!r}")
    print(f"  email       : {contact.get('email')!r}")
    print(f"  phone       : {contact.get('phone')!r}")
    print(f"  summary len : {len(header.get('summary') or '')}")
    print(f"  experience  : {len(exp)} entries")
    for i, e in enumerate(exp[:3]):
        desc_len = len(e.get("description") or "")
        print(f"    [{i}] {e.get('company')!r} | {e.get('title')!r} | desc={desc_len} chars")
    print(f"  projects    : {len(proj)} entries")
    print(f"  skills.tech : {len(skills.get('technical', []))} items -> {skills.get('technical', [])[:8]}")
    print(f"  education   : {len(edu)} entries")
    return {
        "name_ok": bool(header.get("name") and header["name"] != "Unknown"),
        "email_ok": bool(contact.get("email")),
        "exp_count": len(exp),
        "first_desc_len": len((exp[0].get("description") or "") if exp else ""),
        "skills_count": len(skills.get("technical", [])),
        "edu_count": len(edu),
    }


async def test_resume_parser():
    print("\n" + "=" * 60)
    print("TEST 1: 简历解析 LLM vs 正则")
    print("=" * 60)

    if not SAMPLE_PDF.exists():
        print(f"  SKIP: 样本不存在 {SAMPLE_PDF}")
        return None

    print(f"  样本: {SAMPLE_PDF.name}")

    # 正则路径（基线）
    print("\n[1/2] 跑正则路径...")
    regex_parser = ResumeParser(llm_client=None)
    regex_result = await regex_parser.parse(str(SAMPLE_PDF))
    regex_metrics = summarize("正则路径", regex_result)

    # LLM 路径
    print("\n[2/2] 跑 LLM 路径...")
    llm = make_llm()
    llm_parser = ResumeParser(llm_client=llm)
    llm_result = await llm_parser.parse(str(SAMPLE_PDF))
    llm_metrics = summarize("LLM 路径", llm_result)

    # 对比
    print("\n--- 关键指标对比 ---")
    rows = [
        ("name 抽到", regex_metrics["name_ok"], llm_metrics["name_ok"]),
        ("email 抽到", regex_metrics["email_ok"], llm_metrics["email_ok"]),
        ("experience 数量", regex_metrics["exp_count"], llm_metrics["exp_count"]),
        ("首条 description 字符数", regex_metrics["first_desc_len"], llm_metrics["first_desc_len"]),
        ("technical skills 数量", regex_metrics["skills_count"], llm_metrics["skills_count"]),
        ("education 数量", regex_metrics["edu_count"], llm_metrics["edu_count"]),
    ]
    print(f"  {'指标':<30} {'正则':<12} {'LLM':<12}")
    for label, r, l in rows:
        marker = "  ↑" if (isinstance(l, (int,)) and isinstance(r, (int,)) and l > r) else (
            "  ✓" if l == r else ""
        )
        print(f"  {label:<30} {str(r):<12} {str(l):<12}{marker}")

    return llm_result


async def test_url_failure():
    print("\n" + "=" * 60)
    print("TEST 2: URL 路径失败必须 raise，不再 silent return ''")
    print("=" * 60)

    llm = make_llm()
    analyzer = JDAnalyzerEnhanced(llm_client=llm)

    # 测试 1：不存在的通用 URL（必然抓不到正文）
    bad_url = "https://example.com/nonexistent-job-12345"
    print(f"\n[1/2] 通用平台无效 URL: {bad_url}")
    try:
        result = await analyzer.parse_from_url(bad_url)
        # 如果走到这里说明没 raise — 这是 BUG
        print(f"  ❌ FAIL: 应该 raise 但居然返回了结果: title={result.get('title')!r}")
        return False
    except RuntimeError as e:
        print(f"  ✅ PASS: 正确 raise RuntimeError: {str(e)[:100]}")
    except Exception as e:
        print(f"  ✅ PASS: 抛出异常 {type(e).__name__}: {str(e)[:100]}")

    # 测试 2：JobsDB 不存在的 job id
    bad_jobsdb = "https://hk.jobsdb.com/job/00000000"
    print(f"\n[2/2] JobsDB 无效 URL: {bad_jobsdb}")
    print("  （注意：这条会真的启动 Edge 浏览器，看到弹窗属于预期行为）")
    try:
        result = await analyzer.parse_from_url(bad_jobsdb)
        print(f"  ❌ FAIL: 应该 raise 但居然返回了结果: title={result.get('title')!r}")
        return False
    except (RuntimeError, Exception) as e:
        print(f"  ✅ PASS: {type(e).__name__}: {str(e)[:120]}")

    return True


async def main():
    print("\n##########  M2.5 自动化验证  ##########")
    print(f"项目根目录: {PROJECT_ROOT}")
    print(f"模型: {os.getenv('VOLCANO_MODEL', 'agnes-2.0-flash')}")

    # Test 1
    llm_result = await test_resume_parser()

    # Test 2
    url_ok = await test_url_failure()

    print("\n##########  汇总  ##########")
    print(f"  简历解析 LLM 路径:  {'✓ 已跑通' if llm_result else '✗ 跳过'}")
    print(f"  URL 失败 raise 路径: {'✓ 通过' if url_ok else '✗ 失败'}")

    # 把 LLM 抽取结果落盘以便人工抽查
    if llm_result:
        out = PROJECT_ROOT / "data" / "temp" / "m2_5_llm_resume_dump.json"
        out.write_text(json.dumps(llm_result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n  LLM 抽取结果已 dump 到: {out.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    asyncio.run(main())
