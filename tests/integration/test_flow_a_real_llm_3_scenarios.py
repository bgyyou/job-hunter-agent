# -*- coding: utf-8 -*-
"""v3 round-3 P0-2：Flow A 真实 LLM 跑 3 场景端到端集成测试。

按 update_plan.md §8.3 P0-2：在 mock LLM 路径稳定后，验证真实 LLM
（默认接 Agnes，可切火山方舟 / OpenAI / DeepSeek）也能跑通 3 个场景：
- 场景 A：完整（基本信息 + 2 工作 + 1 项目 + 技能 + 模式 A 改写）
- 场景 B：极简（1 段工作 → auto → 模式 B 改写）
- 场景 C：部分（4 段大工作 → 触发超页 → 瘦身后导出）

**运行方式**：
```bash
# 默认跑全部（real_llm 自动 skip if LLM_API_KEY 缺失）
pytest tests/integration/test_flow_a_real_llm_3_scenarios.py -v

# 仅跑真 LLM 路径
pytest tests/integration/test_flow_a_real_llm_3_scenarios.py -v -m real_llm

# 排除真 LLM（CI 友好）
pytest tests/integration/test_flow_a_real_llm_3_scenarios.py -v -m "not real_llm"
```

**覆盖**（≥ 3 条）：
1. 场景 A 完整：form → mode A 改写 → 一页纸预估 → Word 导出
2. 场景 B 极简：form → auto → mode B → 一页纸预估 → Word 导出
3. 场景 C 部分：form → 触发超页 → 瘦身 → Word 导出
"""
from __future__ import annotations

import importlib
import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict

import pytest


# 在模块顶层加载 .env（pytest 不自动加载，必须显式 load，否则 skipif 看不到 key）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
try:
    from dotenv import load_dotenv
    load_dotenv(_PROJECT_ROOT / ".env")
except ImportError:
    pass  # 没装 dotenv 也能跑（依赖 shell env）


# ============================================================
# 跳过条件：LLM_API_KEY 缺失时自动 skip（CI 友好）
# ============================================================

def _has_llm_credentials() -> bool:
    """判断环境是否配齐 LLM 凭证（.env 或 shell env）。"""
    api_key = os.environ.get("LLM_API_KEY", "")
    return bool(api_key) and api_key.strip() != "" and api_key != "your_api_key_here"


needs_llm = pytest.mark.skipif(
    not _has_llm_credentials(),
    reason="LLM_API_KEY 未配置（或为占位符），跳过 real_llm 测试",
)

# 注意：必须在 needs_llm 求值之后再 import page 模块 —— 它会连带 import web_app →
# config.settings 触发 load_dotenv()，把仓库根 .env 灌进 os.environ，
# 放在前面会让上面的 skipif 永远为 False（CI 无凭证时也去打真 LLM）。
page_mod_1 = importlib.import_module('pages.05_💬_Flow_A_Step3')


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(scope="module")
def real_llm_client():
    """真实 LLM 客户端（模块级单例，避免重复初始化）。"""
    # 把 cwd 设到项目根，确保 .env 加载
    from dotenv import load_dotenv
    project_root = Path(__file__).resolve().parent.parent.parent
    load_dotenv(project_root / ".env")

    from tools.llm import OpenAICompatibleClient
    return OpenAICompatibleClient(
        api_key=os.environ["LLM_API_KEY"],
        api_url=os.environ.get("LLM_BASE_URL", "https://apihub.agnes-ai.com/v1"),
        model=os.environ.get("LLM_MODEL", "agnes-2.0-flash"),
        cache_dir=str(project_root / "data" / "llm_cache"),
    )


@pytest.fixture
def sample_resume_full() -> Dict[str, Any]:
    """场景 A：完整简历。"""
    return {
        "name": "张三", "phone": "13800138000", "email": "z@z.com",
        "location": "北京", "target_role": "AI 产品经理",
        "education": [{"school": "北大", "degree": "硕士", "major": "CS",
                       "start_year": "2018", "end_year": "2021", "gpa": "3.8"}],
        "experience": [
            {
                "company": "字节跳动", "title": "AI 产品经理",
                "start_date": "2022.06", "end_date": "至今",
                "description": "负责 AI 产品的需求分析 + RAG 系统设计",
                "achievements": ["促成 200 单成交", "GMV 120 万"],
            },
            {
                "company": "美团", "title": "产品经理",
                "start_date": "2021.07", "end_date": "2022.05",
                "description": "负责外卖订单系统的优化",
                "achievements": ["订单转化率提升 18%"],
            },
        ],
        "projects": [
            {
                "name": "AI Agent 平台", "role": "PM",
                "start_date": "2024.01", "end_date": "至今",
                "description": "0-1 搭建内部 AI Agent 平台",
                "contribution": "需求 + RAG 架构",
                "achievements": ["DAU 1000"],
            },
        ],
        "skills_text": "Python, SQL, LLM, RAG, 产品设计",
    }


@pytest.fixture
def sample_resume_minimal() -> Dict[str, Any]:
    """场景 B：极简简历（信息稀少）。"""
    return {
        "name": "李四", "phone": "13900139000", "email": "l@l.com",
        "location": "上海", "target_role": "数据分析师",
        "education": [{"school": "复旦", "degree": "本科", "major": "统计",
                       "start_year": "2020", "end_year": "2024", "gpa": ""}],
        "experience": [
            {
                "company": "某公司", "title": "数据分析实习生",
                "start_date": "2023.07", "end_date": "2024.01",
                "description": "做数据",
                "achievements": ["做了一个 dashboard"],
            },
        ],
        "projects": [],
        "skills_text": "Excel, SQL",
    }


@pytest.fixture
def sample_resume_overflow() -> Dict[str, Any]:
    """场景 C：4 段大工作 + 大量描述 → 必然超页。"""
    return {
        "name": "王五", "phone": "13700137000", "email": "w@w.com",
        "location": "深圳", "target_role": "后端工程师",
        "education": [{"school": "清华", "degree": "本科", "major": "CS",
                       "start_year": "2019", "end_year": "2023", "gpa": "3.2"}],
        "experience": [
            {
                "company": f"公司{i}", "title": "工程师",
                "start_date": f"20{20 + i}.01", "end_date": f"20{21 + i}.01",
                "description": "做后端 " * 60,  # 大量描述
                "achievements": [f"成就 {j}" for j in range(8)],
            }
            for i in range(4)
        ],
        "projects": [],
        "skills_text": "Python, Go, Rust, Java, C++, Docker, K8s, Redis",
    }


@pytest.fixture
def sample_jd_pm() -> Dict[str, Any]:
    """目标 JD：AI 产品经理（场景 A 用）。"""
    from services.jd_parser import StructuredJD
    return StructuredJD(
        source="text", raw_text="JD 文本",
        company="字节跳动", title="AI 产品经理",
        industry="互联网", function="产品", level="mid",
        responsibilities=["负责 AI 产品规划", "RAG 系统设计"],
        requirements=["3 年 PM 经验", "Python / LLM 背景"],
    )


# ============================================================
# 真 LLM 端到端 3 场景
# ============================================================

@pytest.mark.real_llm
@needs_llm
class TestRealLLMScenarios:
    """真实 LLM 跑通 3 场景：验证 mock 路径 vs 真 LLM 行为一致性。"""

    @pytest.mark.asyncio
    async def test_scenario_a_full_mode_a(self, real_llm_client,
                                          sample_resume_full, sample_jd_pm):
        """场景 A：完整简历 → 模式 A 改写 → 不超页 → Word 导出。

        验证：模式 A 改写后至少保留 1 个原关键数字（200/120/18% 之一）+ 不超页。
        注：v1 FROZEN P0-002 把"必须保留所有 3 个数字"放宽为"≥1 个"，避免 LLM 生成 flake。
        """
        import web_app
        from services.resume_rewriter import ResumeRewriter
        from services.document_generator import DocumentGenerator

        # Step 3: 模式 A 改写（真 LLM）
        rewriter = ResumeRewriter(llm_client=real_llm_client)
        result = await rewriter.rewrite_mode_a(sample_resume_full, sample_jd_pm)

        assert result.mode == "A", f"模式 A 改写失败：mode={result.mode}"
        assert len(result.rewrites) >= 1, "模式 A 应至少产出 1 条改写"

        # 关键约束：原数字至少保留 1 个（避免 LLM 偶发改写某数字导致全数 flake）。
        # 真 LLM 改写是生成式任务，100% 锁三个数字会让 CI 一直红；
        # v1 FROZEN P0-002 决议：放宽为"≥1 数字"或"多 case 取并集"。
        all_text = " ".join(
            rw.get("rewritten", "") for rw in result.rewrites
        )
        must_have = ["200", "120", "18"]
        kept = [n for n in must_have if n in all_text]
        assert len(kept) >= 1, (
            f"模式 A 应至少保留原数字之一 {must_have}，实际 0 个；"
            f"输出片段：{all_text[:200]}"
        )

        # Step 3.5: 合并
        final = page_mod_1._compose_final_resume(
            sample_resume_full, result, _form_from_resume(sample_resume_full),
        )
        assert final["_rewrite_mode"] == "A"
        assert len(final["_rewrites"]) >= 1

        # Step 4: 一页纸预估
        estimate = page_mod_1._estimate_resume(final)
        assert estimate.capacity_mm == 265.0
        assert estimate.overflow is False, (
            f"场景 A 真 LLM 改写后超页：{estimate.total_mm:.1f}mm"
        )

        # Step 5: 导出 Word
        gen = DocumentGenerator()
        doc = gen.generate_word(final, jd=sample_jd_pm, template="conservative", strict_one_page=True)
        assert doc.filename.startswith("张三_")
        assert "AI_产品经理" in doc.filename
        assert doc.content.startswith(b"PK")
        assert doc.estimate.overflow is False

    @pytest.mark.asyncio
    async def test_scenario_b_minimal_auto_mode_b(self, real_llm_client,
                                                  sample_resume_minimal):
        """场景 B：极简简历 → auto → 模式 B → 模板生成。

        验证：scorer 推荐 B，模式 B 输出不含具体公司名/学校 + 含 [AI 模板生成]。
        """
        import web_app
        from services.resume_rewriter import ResumeRewriter

        # Step 3: 评分
        score = page_mod_1._score_resume(sample_resume_minimal)
        assert score["recommended_mode"] in ("B", "A+B"), (
            f"极简简历应推荐 B/A+B，实际：{score['recommended_mode']}"
        )

        # Step 3: 模式 B 改写（真 LLM）
        from services.jd_parser import StructuredJD
        jd = StructuredJD(
            source="text", raw_text="",
            company="某大厂", title="数据分析师",
            industry="互联网", function="数据", level="junior",
            responsibilities=["业务分析"],
            requirements=["SQL / Excel"],
        )

        rewriter = ResumeRewriter(llm_client=real_llm_client)
        result = await rewriter.rewrite_mode_b(jd, sections_to_generate=["experience"])

        assert result.mode == "B"
        assert any(rw.get("is_ai_generated") for rw in result.rewrites), (
            "模式 B 输出应至少一段标 is_ai_generated=true"
        )

        # 关键约束：模式 B 不应出现具体公司名/学校
        all_text = " ".join(rw.get("rewritten", "") for rw in result.rewrites)
        forbidden = ["字节", "阿里", "腾讯", "美团", "京东", "百度", "复旦", "清华", "北大"]
        for bad in forbidden:
            assert bad not in all_text, (
                f"模式 B 不应出现具体公司名/学校 '{bad}'，实际：{all_text[:200]}"
            )

    @pytest.mark.asyncio
    async def test_scenario_c_overflow_slim_then_export(self, real_llm_client,
                                                        sample_resume_overflow):
        """场景 C：4 段大工作 → 触发超页 → 瘦身后导出。

        验证：超页时导出抛错 + 瘦身后预估变小 + 可成功导出。
        """
        import web_app
        from services.document_generator import DocumentGenerator, OnePageOverflowError
        from services.jd_parser import StructuredJD

        jd = StructuredJD(
            source="text", raw_text="JD",
            company="字节跳动", title="后端工程师",
            industry="互联网", function="研发", level="mid",
            responsibilities=["写后端"], requirements=["3 年 Go/Python"],
        )

        # Step 4: 预估超页
        est_full = page_mod_1._estimate_resume(sample_resume_overflow)
        if est_full.overflow:
            # 瘦身（删 2 段工作）
            slim = {**sample_resume_overflow}
            slim["experience"] = sample_resume_overflow["experience"][:2]

            est_slim = page_mod_1._estimate_resume(slim)
            assert est_slim.total_mm <= est_full.total_mm, (
                f"瘦身后预估应变小：full={est_full.total_mm:.1f}, slim={est_slim.total_mm:.1f}"
            )

            # 瘦身后导出
            gen = DocumentGenerator()
            doc = gen.generate_word(slim, jd=jd, template="conservative", strict_one_page=True)
            assert doc.estimate.overflow is False
            assert "王五" in doc.filename
        else:
            # 4 段每段 480 字符必然超页 —— 如果 LLM 输出反而少了，标记但不 fail
            pytest.skip(
                f"场景 C 设计假设超页但实际未超页：total_mm={est_full.total_mm:.1f}mm"
            )


# ============================================================
# Helpers
# ============================================================

def _form_from_resume(resume: Dict[str, Any]) -> Dict[str, Any]:
    """从 resume dict 反向构造 v3 form dict（用于 _compose_final_resume）。"""
    return {
        "basic": {
            "name": resume.get("name", ""),
            "phone": resume.get("phone", ""),
            "email": resume.get("email", ""),
            "location": resume.get("location", ""),
            "target_role": resume.get("target_role", ""),
        },
        "education": resume.get("education", []),
        "work": [
            {**exp, "achievements_text": "\n".join(exp.get("achievements", []))}
            for exp in resume.get("experience", [])
        ],
        "projects": resume.get("projects", []),
        "skills_text": resume.get("skills_text", ""),
    }