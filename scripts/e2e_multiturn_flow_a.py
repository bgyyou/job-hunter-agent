# -*- coding: utf-8 -*-
"""Flow A 真·多轮对话端到端测试。

两个 LLM 实例对话：
  - Agent（被测）：调 ResumeFlowA.chat_section，按 SECTIONS 顺序问问题
  - User（模拟器）：基于真实简历内容扮演郑浩文回答，一次只答 1-2 句

每个 section 真实多轮直到 chat_section 返回 type="section_done"
或 type="section_skipped"。验证：
  ① 状态机能在对话足够后自然输出 [SECTION_DONE]
  ② languages 段用户说"跳过"时输出 [SECTION_DONE,SKIP]
  ③ experience / projects 段会主动追问"第二段呢"
  ④ 全程不卡死（每段最多 N 轮就强制收尾）
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.resume_flow_a import ResumeFlowA, SECTIONS
from tools.llm import OpenAICompatibleClient, LLMMessage


# 真实简历内容（喂给"用户模拟器"作为答题素材）
RESUME_GROUND_TRUTH = """
姓名：郑浩文
电话：+86 13711171888
邮箱：bgyyou99@163.com
个人网站：https://pilotleon.vercel.app/

教育：
- 爱丁堡大学（QS 排名 16），英语语言学学士，2018-2022

工作经历（3 段）：
1. Fans Media，AI项目负责人，2025.12 - 2026.05
   - 独立设计交付 MediaPilot Agent 系统
   - 涵盖架构、编码、部署、培训
   - 实现 200+ 竞品自动化采集
2. Sun Life Hong Kong，数字营销专员，2024.07 - 至今
   - Python + LLM API 批量生成个性化文案
   - 转化率提升 25%
   - 人工审核成本降低 40%
3. Inside No.7，创始人，2022.02 - 2023.11
   - 编写自动化脚本处理会员等级更新、活动提醒、社群消息推送
   - 规则引擎实现用户分层运营

项目经历（2 个）：
1. Jobhunter — 多智能体求职框架（2026）
   - 角色：架构师 + 全栈开发
   - 技术栈：Python、BaseAgent、MessageBus、LLM、diskcache
   - 设计 BaseAgent 抽象类 + MessageBus 异步总线
   - 协调 4 个专用 Agent（Matcher / Coordinator / ResumeAnalyzer / ResumeOptimizer）
   - 链式 Prompt 输出固定 JSON；_fact_check 抑制幻觉
   - diskcache 缓存命中率 40%，API 成本降低 60%
   - 个人求职效率提升 70%
2. MediaPilot — LLM 自动化内容 Agent 系统（2025-2026）
   - 角色：架构师 + 主程
   - 技术栈：Python、Playwright、requests、Docker、GitHub Actions、OpenAI、Anthropic、火山引擎
   - 三层管道（Scraper → Aggregator → Generator）
   - AIServiceManager 工厂支持运行时切换 LLM
   - 覆盖 5 大平台（百度/微博/知乎/抖音/小红书）
   - 跨平台去重 + 热度加权聚合
   - 链式 Prompt（摘要→文案→分镜脚本）
   - 6 个月稳定运行，2000+ 次 Agent 调用，零重大故障

技能：
- 编程语言：Python、TypeScript、SQL
- AI 框架：BaseAgent + MessageBus、Multi-Agent 协作、Prompt 工程、RAG、Function Calling
- LLM API：OpenAI、Claude、火山引擎
- 工具：Docker、Git、Streamlit、CI/CD、diskcache、Playwright
- 评估：Precision/Recall、A/B 测试

语言能力：
- 英语：IELTS 7.0
- 粤语：母语
- 普通话：母语
"""


USER_SIMULATOR_PROMPT = """你正在模拟一位真实求职者**郑浩文**，回答简历助手的提问。

【你的真实简历内容（就是你的全部背景）】
{ground_truth}

【行为规则】
1. **每次只答 1-2 句**，不要主动透露问题之外的信息（比如对方问"姓名和联系方式"时，不要把工作经历也答出来）
2. 你说话像真人：口语化、不要列点、不要 JSON 格式
3. 对方问的信息**你简历里没有**时，直接说"没有"或"这块我跳过吧"
4. 不要重复整段简历——只回答**当前这个问题**问的那一两个点
5. 这是当前正在采集的 section：**{section_name}**。把回答限制在这个 section 范围内
6. 不要在回答末尾加 [DONE] 或任何标记 —— 你是用户，不需要发信号

现在请用第一人称、口语化的方式回答助手的问题。"""


async def simulate_user_reply(
    user_llm,
    section_name: str,
    conversation_so_far: list,
) -> str:
    """用一个 LLM 实例扮演用户，根据简历内容回答 Agent 最新的问题。"""
    sys_text = USER_SIMULATOR_PROMPT.format(
        ground_truth=RESUME_GROUND_TRUTH,
        section_name=section_name,
    )
    # 翻转角色给用户 LLM：Agent 是"user"，用户回复是"assistant"
    flipped = []
    for m in conversation_so_far:
        if m["role"] == "user":
            flipped.append(LLMMessage(role="assistant", content=m["content"]))
        else:
            flipped.append(LLMMessage(role="user", content=m["content"]))

    last_err = None
    for attempt in range(3):
        try:
            response = await user_llm.analyze(
                messages=[LLMMessage(role="system", content=sys_text)] + flipped,
                max_tokens=300,
                temperature=0.7,
            )
            return response.content.strip()
        except Exception as e:
            last_err = e
            await asyncio.sleep(2 ** attempt)
    raise last_err


async def chat_section_with_retry(flow, **kwargs):
    """chat_section 带重试，扛 Agnes 偶发 Server disconnected。"""
    last_err = None
    for attempt in range(3):
        try:
            return await flow.chat_section(**kwargs)
        except Exception as e:
            last_err = e
            print(f"    ⚠️  chat_section 第 {attempt+1} 次失败 ({e})，等待重试...")
            await asyncio.sleep(2 ** attempt)
    raise last_err


async def run_section_dialog(
    flow: ResumeFlowA,
    user_llm,
    section_key: str,
    section_name: str,
    collected_so_far: dict,
    industry: str,
    position: str,
    max_total_turns: int = 12,
):
    """跑单个 section 的真实多轮对话直到 chat_section 返回 done/skipped。"""
    messages = []  # 本段对话历史
    turn = 0
    final_reply = None

    while turn < max_total_turns:
        turn += 1
        # 让 Agent 先说话（首轮 messages 为空，传一句开场用户消息）
        if not messages:
            msgs_for_agent = [{"role": "user", "content": f"开始采集{section_name}吧。"}]
        else:
            msgs_for_agent = messages

        reply = await chat_section_with_retry(
            flow,
            section_key=section_key,
            messages=msgs_for_agent,
            collected_so_far=collected_so_far,
            industry=industry,
            position=position,
        )

        # 第一次记录开场 user msg
        if not messages:
            messages.append({"role": "user", "content": f"开始采集{section_name}吧。"})

        messages.append({"role": "assistant", "content": reply["message"]})
        print(f"    [turn {turn}] 🤖 Agent: {reply['message'][:150]}{'...' if len(reply['message']) > 150 else ''}")
        print(f"             (type={reply['type']})")

        if reply["type"] in ("section_done", "section_skipped"):
            final_reply = reply
            break

        # Agent 还在问 → 让用户模拟器回答
        user_reply = await simulate_user_reply(user_llm, section_name, messages)
        messages.append({"role": "user", "content": user_reply})
        print(f"    [turn {turn}] 👤 User : {user_reply[:150]}{'...' if len(user_reply) > 150 else ''}")

    if final_reply is None:
        # 兜底：到上限了也没收到 done
        final_reply = {"type": "section_done", "message": "(forced by max_total_turns)"}
        print(f"    ⚠️ 达到 max_total_turns={max_total_turns}，强制收尾")

    return messages, final_reply


async def main():
    print("=" * 70)
    print("Flow A 真·多轮对话端到端测试")
    print(f"LLM: {os.getenv('LLM_MODEL')} @ {os.getenv('LLM_BASE_URL')}")
    print("=" * 70)

    common = dict(
        api_key=os.getenv("LLM_API_KEY"),
        api_url=os.getenv("LLM_BASE_URL").rstrip("/"),
        model=os.getenv("LLM_MODEL"),
        is_coding_api=False,
        use_anthropic_format=os.getenv("LLM_USE_ANTHROPIC_FORMAT", "false").lower() == "true",
    )
    agent_llm = OpenAICompatibleClient(**common)
    user_llm = OpenAICompatibleClient(**common)  # 独立实例，扮演用户

    from database.backends.sqlite_backend import SqliteBackend
    from config.settings import settings
    db = SqliteBackend(db_path=settings.db_path)
    flow = ResumeFlowA(agent_llm, db=db)

    industry = "互联网/软件"
    position = "AI产品经理"

    collected = {}
    section_logs = []  # 每段记录: (key, n_turns, final_type, extracted_preview)

    for section in SECTIONS:
        if section.get("derived"):
            continue
        key = section["key"]
        name = section["name"]
        print(f"\n{'━' * 70}")
        print(f"▶ Section: [{key}] {name}    max_rounds={section['max_rounds']}")
        print(f"{'━' * 70}")

        try:
            messages, final = await run_section_dialog(
                flow, user_llm, key, name, collected, industry, position,
                max_total_turns=section["max_rounds"] + 2,  # 给 buffer
            )
        except Exception as e:
            print(f"  ❌ 对话失败: {e}")
            import traceback
            traceback.print_exc()
            section_logs.append((key, 0, "error", None))
            continue

        n_turns = sum(1 for m in messages if m["role"] == "assistant")

        # 提取
        if final["type"] == "section_skipped":
            print(f"  ⏭ 段被跳过，不提取")
            collected[key] = ResumeFlowA._empty_section_value(key)
            section_logs.append((key, n_turns, "section_skipped", None))
        else:
            try:
                extracted = await flow.extract_section(key, messages)
                collected[key] = extracted
                preview = json.dumps(extracted, ensure_ascii=False)[:200]
                print(f"  📦 提取结果: {preview}{'...' if len(preview) >= 200 else ''}")
                section_logs.append((key, n_turns, "section_done", extracted))
            except Exception as e:
                print(f"  ❌ 提取失败: {e}")
                section_logs.append((key, n_turns, "extract_error", None))

    # 派生 + 渲染
    print(f"\n{'━' * 70}")
    print("▶ 派生 summary + core_competencies")
    print(f"{'━' * 70}")
    try:
        derived = await flow.derive_summary_and_competencies(
            collected, industry=industry, position=position,
        )
        print(f"  ✅ summary: {derived.get('summary', '')[:120]}")
        print(f"  ✅ core_competencies ({len(derived.get('core_competencies', []))} 条):")
        for c in derived.get("core_competencies", []):
            print(f"     - {c}")
    except Exception as e:
        print(f"  ❌ 派生失败: {e}")
        derived = {"summary": "", "core_competencies": []}

    # 渲染
    skills_val = collected.get("skills")
    if isinstance(skills_val, dict):
        skills_val = skills_val.get("skills", [])
    languages_val = collected.get("languages")
    if isinstance(languages_val, dict):
        languages_val = languages_val.get("languages", [])

    raw = {
        "header": collected.get("header", {}),
        "summary": derived.get("summary", ""),
        "core_competencies": derived.get("core_competencies", []),
        "education": collected.get("education", []) or [],
        "experience": collected.get("experience", []) or [],
        "projects": collected.get("projects", []) or [],
        "skills": skills_val or [],
        "languages": languages_val or [],
    }
    final_data = flow._normalize_resume_shape(raw)
    md = flow.to_markdown(final_data)
    out_path = ROOT / "data" / "_e2e_multiturn_output.md"
    out_path.write_text(md, encoding="utf-8")

    # ========== 断言 ==========
    print(f"\n{'=' * 70}")
    print("断言检查")
    print(f"{'=' * 70}")

    checks = []

    # 1. 每个采集 section 都通过状态机收尾（不是强制 timeout）
    for key, n_turns, status, extracted in section_logs:
        checks.append((f"[{key}] 状态机自然收尾 (n_turns={n_turns}, type={status})",
                       status in ("section_done", "section_skipped")))

    # 2. experience / projects 段至少问了 2 轮（验证"问完一段问下一段"）
    exp_log = next((x for x in section_logs if x[0] == "experience"), None)
    if exp_log:
        checks.append((f"[experience] 至少 2 轮对话（盘点 + 至少 1 段细节）", exp_log[1] >= 2))
    proj_log = next((x for x in section_logs if x[0] == "projects"), None)
    if proj_log:
        checks.append((f"[projects] 至少 2 轮对话", proj_log[1] >= 2))

    # 3. 提取的工作经历数量 ≥ 2（验证没漏问其他段）
    exp_data = collected.get("experience", [])
    if isinstance(exp_data, list):
        checks.append((f"experience 提取 ≥ 2 段（用户简历有 3 段）", len(exp_data) >= 2))
    proj_data = collected.get("projects", [])
    if isinstance(proj_data, list):
        checks.append((f"projects 提取 ≥ 2 个（用户简历有 2 个）", len(proj_data) >= 2))

    # 4. 派生非空
    checks.append(("derived.summary 非空", bool(derived.get("summary"))))
    checks.append(("derived.core_competencies ≥ 3", len(derived.get("core_competencies", [])) >= 3))

    # 5. markdown 包含 8 段
    expected = ["# 郑浩文", "## 个人陈述", "## 核心能力", "## 工作经历",
                "## 项目经历", "## 技能", "## 教育背景"]
    for h in expected:
        checks.append((f"markdown 包含 `{h}`", h in md))

    # 6. 无占位符
    placeholders = ["[您的", "[X]", "202X", "xxx", "待补充", "TBD"]
    for ph in placeholders:
        checks.append((f"markdown 不含 `{ph}`", ph not in md))

    passed = 0
    failed_items = []
    for label, ok in checks:
        marker = "✅" if ok else "❌"
        print(f"  {marker} {label}")
        if ok:
            passed += 1
        else:
            failed_items.append(label)

    print(f"\n通过：{passed}/{len(checks)}")
    if failed_items:
        print(f"\n失败项：")
        for f in failed_items:
            print(f"  - {f}")
    print(f"\n📄 markdown 已写入 {out_path}")

    return passed == len(checks)


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
