# -*- coding: utf-8 -*-
"""P1-2 端到端测试：简历 Flow B (修改 → 生成)

覆盖链路（用户原话"还需要进行测试"）：
  resume_data + jd_result + recommendations
    → ResumeOptimizer.optimize()  (mock LLM)
    → ResumeGenerator.to_markdown()
    → ResumeGenerator.to_html()
    → ResumeGenerator.generate_pdf(format='markdown')  避免依赖 weasyprint
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from tools.generator.resume_optimizer import ResumeOptimizer
from tools.generator.resume_generator import ResumeGenerator
from tools.llm import LLMResponse


def _resume_input():
    return {
        "header": {
            "name": "Leon",
            "contact": {"phone": "12345", "email": "leon@e.com"},
            "summary": "5 年产品经理，专注 AI 工具方向",
        },
        "experience": [
            {
                "title": "高级产品经理",
                "company": "ACME",
                "duration": "2022-至今",
                "achievements": ["主导某 SaaS 产品 0-1 落地"],
            }
        ],
        "skills": ["Python", "SQL", "需求分析"],
        "education": [{"school": "CUHK", "degree": "硕士", "major": "信息系统"}],
    }


def _jd_input():
    return {
        "title": "AI 产品经理",
        "company": "DeepSearch",
        "core_requirements": ["LLM 应用经验", "RAG 系统设计"],
        "keywords": ["LLM", "RAG", "Agent"],
    }


def _recommendations():
    return [
        {"type": "modify", "section": "summary", "reason": "强化 LLM 经验描述"},
        {"type": "suggest_add", "section": "skills", "reason": "补充 LLM/RAG 关键词"},
    ]


def _optimized_response_json() -> str:
    """LLM 返回的 mock 内容：在原简历基础上加了 LLM/RAG 关键词"""
    optimized = _resume_input()
    optimized["header"]["summary"] = "5 年产品经理，专注 AI 工具与 LLM 应用方向"
    optimized["skills"] = ["Python", "SQL", "需求分析", "LLM", "RAG"]
    return json.dumps(optimized, ensure_ascii=False)


def _mock_llm():
    """模拟 LLMClient，固定返回优化后的 JSON"""
    client = AsyncMock()
    client.analyze = AsyncMock(
        return_value=LLMResponse(
            content=_optimized_response_json(),
            model="mock",
            tokens_used=100,
            finish_reason="stop",
        )
    )
    return client


# -------- Step 1：Optimizer 单元 --------

def test_optimizer_returns_dict_with_added_keywords():
    """LLM 输出能被解析回 dict，并包含新增的 LLM/RAG 关键词"""
    optimizer = ResumeOptimizer(_mock_llm())
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(
            optimizer.optimize(_resume_input(), _jd_input(), _recommendations())
        )
    finally:
        loop.close()
    assert isinstance(result, dict)
    assert "LLM" in result["skills"]
    assert "RAG" in result["skills"]
    assert "LLM" in result["header"]["summary"]


def test_optimizer_falls_back_to_original_on_bad_json():
    """LLM 返回非 JSON 时，应回退到原始简历，不抛异常"""
    client = AsyncMock()
    client.analyze = AsyncMock(
        return_value=LLMResponse(
            content="抱歉，我无法生成 JSON。",
            model="mock", tokens_used=10, finish_reason="stop",
        )
    )
    optimizer = ResumeOptimizer(client)
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(
            optimizer.optimize(_resume_input(), _jd_input(), [])
        )
    finally:
        loop.close()
    # 应原样返回
    assert result == _resume_input()


# -------- Step 2：Generator markdown --------

def test_generator_markdown_contains_name_and_sections():
    md = ResumeGenerator().to_markdown(_resume_input())
    assert "# Leon" in md
    assert "## 个人陈述" in md
    assert "## 工作经历" in md
    assert "ACME" in md


# -------- Step 3：Generator HTML --------

def test_generator_html_well_formed():
    html = ResumeGenerator().to_html(_resume_input())
    assert "<!DOCTYPE html>" in html
    assert "<html" in html and "</html>" in html
    assert "Leon" in html


# -------- Step 4：完整 Flow B 端到端 --------

def test_flow_b_end_to_end_markdown(tmp_path: Path):
    """
    端到端：原始简历 → Optimizer (mock LLM) → Generator → 写 markdown 文件
    这一路通了，说明 web_app.py 那个"生成优化简历"按钮的核心链路是健康的。
    """
    optimizer = ResumeOptimizer(_mock_llm())
    generator = ResumeGenerator()

    loop = asyncio.new_event_loop()
    try:
        optimized = loop.run_until_complete(
            optimizer.optimize(_resume_input(), _jd_input(), _recommendations())
        )
        out_path = tmp_path / "resume_test"
        result_path = loop.run_until_complete(
            generator.generate_pdf(optimized, str(out_path), output_format="markdown")
        )
    finally:
        loop.close()

    written = Path(result_path)
    assert written.exists()
    text = written.read_text(encoding="utf-8")
    # 验证 LLM 优化的内容确实进入了最终产物
    assert "LLM" in text
    assert "RAG" in text
    assert "Leon" in text


def test_flow_b_end_to_end_html(tmp_path: Path):
    """同上，但走 HTML 通路（生产可直接 PDF 化）"""
    optimizer = ResumeOptimizer(_mock_llm())
    generator = ResumeGenerator()

    loop = asyncio.new_event_loop()
    try:
        optimized = loop.run_until_complete(
            optimizer.optimize(_resume_input(), _jd_input(), _recommendations())
        )
        out_path = tmp_path / "resume_test"
        result_path = loop.run_until_complete(
            generator.generate_pdf(optimized, str(out_path), output_format="html")
        )
    finally:
        loop.close()

    written = Path(result_path)
    assert written.exists()
    assert written.suffix == ".html"
    text = written.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in text
    assert "LLM" in text
