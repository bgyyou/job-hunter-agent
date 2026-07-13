# -*- coding: utf-8 -*-
"""v3 round-2: Flow A 5 Step 端到端集成测试（T10 - 3 手动场景等价）

按 update_plan.md §8.2 T10：
- 场景 A：完整（基本+多段+项目+技能，模式 A 改写）
- 场景 B：极简（1 段工作，auto → B 改写）
- 场景 C：部分（空白大段，模式 B 模板，可能超页 → 触发瘦身）

3 个场景用 fake LLM（mock 信息量评分 + 改写器）端到端跑通
Step 1（解析）→ Step 2（转换）→ Step 3（改写）→ Step 4（预估）→ Step 5（导出）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest

import web_app
from services.jd_parser import StructuredJD, JDParserRouter
from services.resume_rewriter import ResumeRewriter, RewriteResult


# ============================================================
# Fixtures：3 个手动场景
# ============================================================

@pytest.fixture
def scenario_a_full():
    """场景 A：完整简历（基本+2 工作+1 项目+技能+语言+证书+作品集）。"""
    return {
        "form": {
            "basic": {
                "name": "张三", "phone": "13800138000", "email": "z@z.com",
                "location": "北京", "target_role": "AI 产品经理", "gender": "男",
                "birth_year": "1995",
            },
            "education": [
                {"school": "北大", "degree": "硕士", "major": "CS",
                 "start_year": "2018", "end_year": "2021", "gpa": "3.8"},
            ],
            "work": [
                {
                    "company": "字节跳动", "title": "AI 产品经理",
                    "start_date": "2022.06", "end_date": "至今",
                    "description": "负责 AI 产品的需求分析 + RAG 系统设计",
                    "achievements_text": "促成 200 单成交\nGMV 120 万",
                },
                {
                    "company": "美团", "title": "产品经理",
                    "start_date": "2021.07", "end_date": "2022.05",
                    "description": "负责外卖订单系统的优化",
                    "achievements_text": "订单转化率提升 18%",
                },
            ],
            "projects": [
                {
                    "name": "AI Agent 平台", "role": "PM",
                    "start_date": "2024.01", "end_date": "至今",
                    "description": "0-1 搭建内部 AI Agent 平台",
                    "contribution": "需求 + RAG 架构",
                    "achievements_text": "DAU 1000",
                },
            ],
            "skills_text": "Python, SQL, LLM, RAG, 产品设计",
            "certifications_text": "PMP",
            "languages_text": "中文, 英语（CET-6）",
            "portfolio": "github.com/zhangsan",
        },
        "jd": StructuredJD(
            source="text", raw_text="JD 文本",
            company="字节跳动", title="AI 产品经理",
            industry="互联网", function="产品", level="mid",
            responsibilities=["负责 AI 产品规划", "RAG 系统设计"],
            requirements=["3 年 PM 经验", "Python / LLM 背景"],
        ),
    }


@pytest.fixture
def scenario_b_minimal():
    """场景 B：极简简历（1 段工作，auto 推荐 B）。"""
    return {
        "form": {
            "basic": {
                "name": "李四", "phone": "13900139000", "email": "l@l.com",
                "location": "上海", "target_role": "数据分析师", "gender": "",
                "birth_year": "",
            },
            "education": [
                {"school": "复旦", "degree": "本科", "major": "统计",
                 "start_year": "2020", "end_year": "2024", "gpa": ""},
            ],
            "work": [
                {
                    "company": "某公司", "title": "数据分析实习生",
                    "start_date": "2023.07", "end_date": "2024.01",
                    "description": "做数据",
                    "achievements_text": "做了一个 dashboard",
                },
            ],
            "projects": [],
            "skills_text": "Excel, SQL",
            "certifications_text": "",
            "languages_text": "中文",
            "portfolio": "",
        },
        "jd": StructuredJD(
            source="rag", raw_text="",
            company="某大厂", title="数据分析师",
            industry="互联网", function="数据", level="junior",
            responsibilities=["业务分析"],
            requirements=["SQL / Excel"],
        ),
    }


@pytest.fixture
def scenario_c_partial():
    """场景 C：部分简历（多段+大量描述，可能触发超页）。"""
    return {
        "form": {
            "basic": {
                "name": "王五", "phone": "13700137000", "email": "w@w.com",
                "location": "深圳", "target_role": "后端工程师", "gender": "",
                "birth_year": "",
            },
            "education": [
                {"school": "清华", "degree": "本科", "major": "CS",
                 "start_year": "2019", "end_year": "2023", "gpa": "3.2"},
            ],
            "work": [
                {
                    "company": f"公司{i}", "title": "工程师",
                    "start_date": f"20{20 + i}.01", "end_date": f"20{21 + i}.01",
                    "description": "做后端 " * 60,  # 大量描述
                    "achievements_text": "\n".join([f"成就 {j}" for j in range(8)]),
                }
                for i in range(4)
            ],
            "projects": [],
            "skills_text": "Python, Go, Rust, Java, C++, Docker, K8s, Redis, PG, MySQL",
            "certifications_text": "",
            "languages_text": "中文",
            "portfolio": "",
        },
        "jd": StructuredJD(
            source="text", raw_text="JD 文本",
            company="字节跳动", title="后端工程师",
            industry="互联网", function="研发", level="mid",
            responsibilities=["写后端"],
            requirements=["3 年 Go/Python"],
        ),
    }


# ============================================================
# Mock LLM
# ============================================================

class _FakeLLM:
    """返回信息量评分 + 改写结果（不走真 LLM）。"""

    def __init__(self, mode: str = "A"):
        self.mode = mode
        self.calls: list = []

    async def analyze(self, messages, system_prompt=None, **kwargs):
        from tools.llm import LLMResponse
        self.calls.append({"system": system_prompt})
        if "MODE_A" in (system_prompt or ""):
            content = '{"rewrites": [{"original": "原段", "rewritten": "改写段（结果导向）", "rewrite_reason": "对接 JD"}]}'
        else:  # MODE_B
            content = '{"templates": [{"section": "experience", "content": "月均获客 500-1000 [AI 模板生成]", "anchored_keywords": ["获客"], "is_ai_generated": true}]}'
        return LLMResponse(content=content, model="fake", tokens_used=10, finish_reason="stop")

    async def analyze_with_structured_output(self, messages, output_schema, **kwargs):
        return {"company": "字节跳动", "title": "AI 产品经理", "industry": "互联网",
                "function": "产品", "level": "mid",
                "responsibilities": ["A"], "requirements": ["B"]}


# ============================================================
# 场景 A：完整流程（JD 文本 → 表单完整 → 模式 A → 不超页 → 导出）
# ============================================================

class TestScenarioAFull:
    def test_full_flow(self, scenario_a_full):
        """Step 1 解析 → Step 2 form → Step 3 改写 → Step 4 预估 → Step 5 导出。"""
        form = scenario_a_full["form"]
        jd = scenario_a_full["jd"]

        # Step 2: form → resume
        resume = web_app.step2_form_to_resume(form)
        assert resume["name"] == "张三"
        assert len(resume["experience"]) == 2
        assert len(resume["projects"]) == 1

        # Step 3: 模式 A 改写
        import asyncio
        rewriter = ResumeRewriter(llm_client=_FakeLLM(mode="A"))
        result = asyncio.run(rewriter.rewrite_mode_a(resume, jd))
        assert result.mode == "A"
        assert len(result.rewrites) >= 1

        # Step 3.5: 合并 final_resume
        final = web_app._compose_final_resume(resume, result, form)
        assert final["_rewrite_mode"] == "A"
        assert len(final["_rewrites"]) >= 1

        # Step 4: 一页纸预估
        estimate = web_app._estimate_resume(final)
        assert estimate.capacity_mm == 265.0
        # 完整简历但每段 60-100 字符 → 应该在 1 页内
        assert estimate.overflow is False, (
            f"场景 A 不应超页：total_mm={estimate.total_mm:.1f} "
            f"segments={estimate.segment_lines}"
        )

        # Step 5: 导出 Word
        from services.document_generator import DocumentGenerator
        gen = DocumentGenerator()
        # mock document_generator 接受 dict / dict 输入
        result_doc = gen.generate_word(final, jd=jd, template="conservative", strict_one_page=True)
        assert result_doc.filename.startswith("张三_")
        assert "AI_产品经理" in result_doc.filename
        assert "字节跳动" in result_doc.filename
        assert result_doc.content.startswith(b"PK")
        assert result_doc.estimate.overflow is False


# ============================================================
# 场景 B：极简流程（JD RAG → 极简表单 → auto → 模式 B → 导出）
# ============================================================

class TestScenarioBMinimal:
    def test_minimal_flow(self, scenario_b_minimal):
        form = scenario_b_minimal["form"]
        jd = scenario_b_minimal["jd"]

        # Step 2
        resume = web_app.step2_form_to_resume(form)
        assert len(resume["experience"]) == 1
        assert resume["projects"] == []

        # Step 3: 评分
        score = web_app._score_resume(resume)
        assert score["recommended_mode"] in ("B", "A+B")
        # 极简简历 → 推荐 B

        # Step 3: 模式 B 改写
        import asyncio
        rewriter = ResumeRewriter(llm_client=_FakeLLM(mode="B"))
        result = asyncio.run(rewriter.rewrite_mode_b(jd, sections_to_generate=["experience"]))
        assert result.mode == "B"
        assert any(rw.get("is_ai_generated") for rw in result.rewrites)

        # Step 3.5: 合并
        final = web_app._compose_final_resume(resume, result, form)
        assert final["_rewrite_mode"] == "B"

        # Step 4: 预估
        estimate = web_app._estimate_resume(final)
        assert estimate.overflow is False

        # Step 5: 导出
        from services.document_generator import DocumentGenerator
        gen = DocumentGenerator()
        result_doc = gen.generate_word(final, jd=jd, template="modern", strict_one_page=True)
        assert "李四" in result_doc.filename
        assert "数据分析师" in result_doc.filename


# ============================================================
# 场景 C：部分流程（4 段工作 + 大量描述 → 触发超页 + 瘦身）
# ============================================================

class TestScenarioCPartial:
    def test_overflow_triggers_slim(self, scenario_c_partial):
        form = scenario_c_partial["form"]
        jd = scenario_c_partial["jd"]

        # Step 2
        resume = web_app.step2_form_to_resume(form)
        assert len(resume["experience"]) == 4

        # Step 4: 预估 — 4 段大工作 → 必然超页
        estimate = web_app._estimate_resume(resume)
        # 4 段工作 + 大量描述 → 应超页
        if estimate.overflow:
            # 超页 → 瘦身建议应触发
            assert any(s for s in estimate.suggestions), "超页时应有瘦身建议"
            assert "experience" in estimate.overflow_segments

        # Step 5: 严格一页导出 → 应抛错
        from services.document_generator import DocumentGenerator, OnePageOverflowError
        gen = DocumentGenerator()
        with pytest.raises(OnePageOverflowError):
            gen.generate_word(
                resume, jd=jd, template="conservative", strict_one_page=True,
            )

        # 模拟用户瘦身（删 2 段工作）后预估
        resume_slim = {**resume}
        resume_slim["experience"] = resume["experience"][:2]
        estimate_slim = web_app._estimate_resume(resume_slim)
        # 瘦身后应不超页（或至少溢出量变小）
        assert estimate_slim.total_mm <= estimate.total_mm

        # 瘦身后可导出
        result_doc = gen.generate_word(
            resume_slim, jd=jd, template="conservative", strict_one_page=True,
        )
        assert "王五" in result_doc.filename
        assert result_doc.estimate.overflow is False
