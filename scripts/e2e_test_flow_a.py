# -*- coding: utf-8 -*-
"""Flow A section 状态机端到端测试（真实 LLM）。

用 桌面/面试/简历/Zheng Haowen CV(AI Agent) - 中文.docx 的内容
喂给每个 section 的 extract_section，串完整链路验证：
  ① 8 段都被采集到非空数据
  ② 派生 summary + core_competencies 是非空、不含占位符
  ③ 最终 markdown 包含所有段
  ④ 不出 [您的姓名] / 202X 这种占位符
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

# 加载 .env
from dotenv import load_dotenv
load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.resume_flow_a import ResumeFlowA, SECTIONS
from tools.llm import OpenAICompatibleClient


# 把用户的真实简历内容拆给每个 section（模拟"用户在每个 section 回答了什么"）
# 注：现实里每段会 2-3 轮 chat_section 对话，但 extract_section 的输入只依赖
# 对话历史里有什么文本。我们直接拼一段"用户描述"作为 user message。
SECTION_USER_ANSWERS = {
    "header": (
        "我叫郑浩文。电话 +86 13711171888，邮箱 bgyyou99@163.com，"
        "个人网站 https://pilotleon.vercel.app/。"
    ),
    "education": (
        "我本科在爱丁堡大学（QS 排名 16），主修英语语言学，学士学位。"
    ),
    "experience": (
        "我有 3 段相关工作经历。"
        "\n第 1 段：Fans Media，AI 项目负责人，2025 年 12 月到 2026 年 5 月。"
        "独立设计交付 MediaPilot Agent 系统，涵盖架构、编码、部署、培训；实现 200+ 竞品自动化采集。"
        "\n第 2 段：Sun Life Hong Kong，数字营销专员，2024 年 7 月到至今。"
        "使用 Python 脚本 + LLM API 批量生成个性化文案，转化率提升 25%，人工审核成本降低 40%。"
        "\n第 3 段：Inside No.7，创始人，2022 年 2 月到 2023 年 11 月。"
        "编写自动化脚本处理会员等级更新、活动提醒及社群消息推送，基于规则引擎实现用户分层运营。"
    ),
    "projects": (
        "我有 2 个想重点突出的项目。"
        "\n项目 1：Jobhunter — 多智能体求职框架（2026 年）。"
        "我是架构师 + 全栈开发。技术栈：Python、BaseAgent、MessageBus、LLM、diskcache。"
        "设计 BaseAgent 抽象类 + MessageBus 异步总线，协调 4 个专用 Agent（Matcher / Coordinator / ResumeAnalyzer / ResumeOptimizer）。"
        "链式 Prompt 让 LLM 输出固定 JSON（0-100 分 + 理由 + 缺失关键词）；_fact_check 模块交叉验证抑制幻觉。"
        "diskcache 缓存 LLM 请求，重复命中率 40%，API 成本降低 60%。个人求职效率提升 70%。"
        "\n项目 2：MediaPilot — LLM 自动化内容 Agent 系统（2025-2026 年）。"
        "我是架构师 + 主程。技术栈：Python、Playwright、requests、Docker、GitHub Actions、OpenAI、Anthropic、火山引擎。"
        "三层服务管道（Scraper → Aggregator → Generator）；AIServiceManager 工厂支持运行时切换 LLM 提供商。"
        "覆盖 5 大平台（百度/微博/知乎/抖音/小红书）；跨平台去重 + 热度加权聚合；链式调用 3 个 Prompt（摘要→文案→分镜脚本）。"
        "内容团队效率提升 70%，稳定运行 6 个月处理 2000+ 次 Agent 调用，零重大故障。"
    ),
    "skills": (
        "技术栈：Python、TypeScript、SQL、Docker、Git、Streamlit。"
        "AI 相关：BaseAgent、MessageBus、Multi-Agent 协作、Prompt 工程、RAG、Function Calling、"
        "OpenAI API、Claude API、火山引擎、diskcache 缓存优化。"
        "工程化：CI/CD、异步重试与超时控制、Precision/Recall 评估、A/B 测试。"
    ),
    "languages": (
        "英语：IELTS 7.0。粤语：母语。普通话：母语。"
    ),
}


async def main():
    print("=" * 70)
    print("Flow A section 状态机端到端测试")
    print(f"LLM: {os.getenv('LLM_MODEL')} @ {os.getenv('LLM_BASE_URL')}")
    print("=" * 70)

    # 初始化真实 LLM
    llm_client = OpenAICompatibleClient(
        api_key=os.getenv("LLM_API_KEY"),
        api_url=os.getenv("LLM_BASE_URL").rstrip("/"),
        model=os.getenv("LLM_MODEL"),
        is_coding_api=False,
        use_anthropic_format=os.getenv("LLM_USE_ANTHROPIC_FORMAT", "false").lower() == "true",
    )

    from database.backends.sqlite_backend import SqliteBackend
    from config.settings import settings
    db = SqliteBackend(db_path=settings.db_path)

    flow = ResumeFlowA(llm_client, db=db)

    industry = "互联网/软件"
    position = "AI产品经理"

    collected = {}
    pass_marks = []

    # --- 跑每个采集 section 的 extract_section ---
    for section in SECTIONS:
        if section.get("derived"):
            continue
        key = section["key"]
        name = section["name"]
        print(f"\n[{key}] {name} — extract_section ...")

        user_answer = SECTION_USER_ANSWERS.get(key, "")
        messages = [
            {"role": "assistant", "content": f"请告诉我你的{name}。"},
            {"role": "user", "content": user_answer},
        ]
        try:
            extracted = await flow.extract_section(key, messages)
        except Exception as e:
            print(f"  ❌ 失败: {e}")
            pass_marks.append((key, False))
            continue

        collected[key] = extracted
        preview = json.dumps(extracted, ensure_ascii=False)[:200]
        print(f"  ✅ 输出: {preview}{'...' if len(preview) >= 200 else ''}")
        pass_marks.append((key, bool(extracted)))

    # --- 派生 summary + core_competencies ---
    print(f"\n[derive] summary + core_competencies ...")
    try:
        derived = await flow.derive_summary_and_competencies(collected, industry=industry, position=position)
        print(f"  ✅ summary: {derived.get('summary', '')[:100]}")
        print(f"  ✅ core_competencies: {derived.get('core_competencies', [])}")
        pass_marks.append(("derive", bool(derived.get("summary")) and bool(derived.get("core_competencies"))))
    except Exception as e:
        print(f"  ❌ 失败: {e}")
        derived = {"summary": "", "core_competencies": []}
        pass_marks.append(("derive", False))

    # --- 组装 + normalize + 渲染 ---
    print(f"\n[render] normalize + to_markdown ...")
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
    final = flow._normalize_resume_shape(raw)
    md = flow.to_markdown(final)

    out_path = ROOT / "data" / "_e2e_resume_output.md"
    out_path.write_text(md, encoding="utf-8")
    print(f"  ✅ markdown 已写入 {out_path} ({len(md)} chars)")

    # --- 断言检查 ---
    print(f"\n" + "=" * 70)
    print("断言检查")
    print("=" * 70)

    checks = []

    # 1. 8 段都非空（不算 derive，那是 derived）
    for section in SECTIONS:
        if section.get("derived"):
            continue
        k = section["key"]
        v = collected.get(k)
        # 容忍空 list（用户跳过）但本测试中应全有
        is_nonempty = bool(v) and v != [] and v != {}
        checks.append((f"section[{k}] 非空", is_nonempty))

    # 2. derived 非空
    checks.append(("derived.summary 非空", bool(derived.get("summary"))))
    checks.append(("derived.core_competencies ≥3", len(derived.get("core_competencies", [])) >= 3))

    # 3. markdown 包含所有段标题
    expected_headers = ["# 郑浩文", "## 个人陈述", "## 核心能力", "## 工作经历",
                        "## 项目经历", "## 技能", "## 教育背景", "## 语言能力"]
    for h in expected_headers:
        checks.append((f"markdown 包含 `{h}`", h in md))

    # 4. 不出占位符
    placeholders = ["[您的", "[X]", "202X", "[前一家", "xxx", "XXX", "待补充", "TBD", "[待"]
    for ph in placeholders:
        checks.append((f"markdown 不含占位符 `{ph}`", ph not in md))

    # 5. 真实数据出现
    real_data = ["郑浩文", "bgyyou99", "Fans Media", "Sun Life", "Jobhunter",
                 "MediaPilot", "爱丁堡", "Python", "IELTS"]
    for rd in real_data:
        checks.append((f"markdown 包含真实数据 `{rd}`", rd in md))

    passed = 0
    for label, ok in checks:
        marker = "✅" if ok else "❌"
        print(f"  {marker} {label}")
        if ok:
            passed += 1

    print(f"\n通过：{passed}/{len(checks)}")
    print(f"\n--- 最终 markdown 预览 ---\n")
    print(md)

    return passed == len(checks)


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
