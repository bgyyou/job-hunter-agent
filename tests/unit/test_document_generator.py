"""v3 M-rebuild-3: 文档生成器测试

覆盖：
- 文件命名 `{姓名}_{岗位}_{公司}.{ext}` + 特殊字符过滤
- 一页纸强校验（超页抛 OnePageOverflowError）
- 双模板（conservative / modern）都生成成功
- LLM 不可用降级（document_generator 不依赖 LLM，纯模板渲染）
- jd 缺省时 fallback 文件名
"""
import pytest
from dataclasses import dataclass, field
from typing import List, Optional

from services.document_generator import (
    DocumentGenerator,
    DocumentResult,
    OnePageOverflowError,
    DocumentGenerationError,
    suggest_filename,
    sanitize_filename_part,
)


# ============================================================
# Fixtures
# ============================================================

@dataclass
class Edu:
    school: str
    degree: str
    major: str
    start_year: int
    end_year: int


@dataclass
class Exp:
    company: str
    title: str
    description: str = ""
    start_date: str = ""
    end_date: str = "至今"
    achievements: list = field(default_factory=list)


@pytest.fixture
def minimal_resume():
    """刚好一页的最小简历。"""
    return {
        "name": "张三",
        "phone": "13800138000",
        "email": "zhangsan@example.com",
        "target_roles": ["Python 工程师"],
        "summary": "3 年 Python 后端经验",
        "experience": [
            Exp(
                company="字节跳动", title="Python 开发",
                start_date="2022.06", end_date="至今",
                description="负责后端服务开发", achievements=["促成 200 单成交"],
            )
        ],
        "education": [Edu(school="北大", degree="本科", major="CS", start_year=2018, end_year=2022)],
        "skills": ["Python", "Django", "PG", "Redis"],
    }


@pytest.fixture
def overflow_resume():
    """明显超页的简历。"""
    big_exp = [
        Exp(company=f"C{i}", title="T", description="x" * 400, achievements=["a"] * 10)
        for i in range(5)
    ]
    return {
        "name": "李四",
        "phone": "138",
        "email": "lisi@example.com",
        "experience": big_exp,
        "skills": ["Python"] * 20,
        "achievements": [f"成就{i}" for i in range(10)],
    }


@pytest.fixture
def jd():
    return {
        "company": "字节跳动",
        "title": "AI 产品经理",
        "industry": "互联网",
        "function": "产品",
    }


@pytest.fixture
def gen():
    return DocumentGenerator()


# ============================================================
# 文件命名
# ============================================================

class TestSuggestFilename:
    """文件命名 `{姓名}_{岗位}_{公司}.{ext}` + 特殊字符过滤。"""

    def test_normal(self):
        # sanitize 把空格也压成 _（保持 filename-safe）
        assert suggest_filename("张三", "AI 产品经理", "字节跳动", ext="docx") == \
            "张三_AI_产品经理_字节跳动.docx"

    def test_pdf_extension(self):
        f = suggest_filename("张三", "PM", "字节跳动", ext="pdf")
        assert f.endswith(".pdf")
        assert f.startswith("张三_")

    def test_strip_special_chars(self):
        """Windows 非法字符 <>:\"/\\|?* 必须过滤。"""
        f = suggest_filename('张<三>"', "P/M", "字?节", ext="docx")
        assert "<" not in f
        assert ">" not in f
        assert '"' not in f
        assert "?" not in f
        assert "/" not in f
        assert "\\" not in f

    def test_empty_part_uses_fallback(self):
        f = suggest_filename("", "", "", ext="docx")
        # 全空 → 各部分用 fallback
        assert "简历" in f
        assert "岗位" in f
        assert "公司" in f
        assert f.endswith(".docx")

    def test_partial_empty(self):
        """公司为空时用 fallback，不抛异常。"""
        f = suggest_filename("张三", "PM", "", ext="docx")
        assert "张三" in f
        assert "公司" in f  # fallback

    def test_truncate_long_name(self):
        """超长名字截断到 40 字符。"""
        long_name = "x" * 100
        part = sanitize_filename_part(long_name)
        assert len(part) <= 40

    def test_sanitize_only_special_chars(self):
        """纯特殊字符 → fallback。"""
        assert sanitize_filename_part("<>:\"/\\|?*") == "未命名"


# ============================================================
# Word 生成
# ============================================================

class TestGenerateWord:
    """generate_word：python-docx + jinja2。"""

    def test_conservative_minimal(self, gen, minimal_resume, jd):
        """保守模板 + 最小简历 → 生成成功。"""
        result = gen.generate_word(minimal_resume, jd, template="conservative")
        assert isinstance(result, DocumentResult)
        assert result.content.startswith(b"PK")  # docx 是 ZIP
        assert result.filename.endswith(".docx")
        assert "张三" in result.filename
        # sanitize 把 "AI 产品经理" 压成 "AI_产品经理"
        assert "AI_产品经理" in result.filename
        assert "字节跳动" in result.filename

    def test_modern_template(self, gen, minimal_resume, jd):
        """现代模板 + 最小简历 → 生成成功 + 包含目标岗位标注。"""
        result = gen.generate_word(minimal_resume, jd, template="modern")
        assert result.template_used == "modern"
        assert result.filename.endswith(".docx")

    def test_unknown_template_raises(self, gen, minimal_resume, jd):
        """不存在模板 → DocumentGenerationError。"""
        with pytest.raises(DocumentGenerationError, match="模板不存在"):
            gen.generate_word(minimal_resume, jd, template="nonexistent")

    def test_overflow_strict_raises(self, gen, overflow_resume, jd):
        """超页 + strict_one_page=True → OnePageOverflowError。"""
        with pytest.raises(OnePageOverflowError) as exc:
            gen.generate_word(overflow_resume, jd, template="conservative")
        # 异常应含估算信息
        assert exc.value.estimate.overflow is True
        assert len(exc.value.estimate.suggestions) > 0

    def test_overflow_non_strict_passes(self, gen, overflow_resume, jd):
        """超页 + strict_one_page=False → 不抛异常（生成可能不美观但通过）。"""
        result = gen.generate_word(
            overflow_resume, jd, template="conservative", strict_one_page=False
        )
        assert result.content  # 仍生成
        assert result.estimate.overflow is True  # 估算仍标 overflow

    def test_filename_with_empty_jd(self, gen, minimal_resume):
        """jd 缺省 → 文件名用 fallback（"通用岗位"/"公司"）。"""
        result = gen.generate_word(minimal_resume, jd=None, template="conservative")
        assert "张三" in result.filename
        assert "通用岗位" in result.filename or "岗位" in result.filename

    def test_no_llm_needed(self, gen, minimal_resume, jd):
        """document_generator 不依赖 LLM（纯模板渲染）。"""
        # 不注入 llm_client 也能工作
        result = gen.generate_word(minimal_resume, jd, template="conservative")
        assert result.content
        # 这是模板系统的核心边界——必须不依赖外部 LLM
        assert "wordprocessingml" in result.mime_type
        assert result.filename.endswith(".docx")

    def test_dict_or_dataclass_input(self, gen, jd):
        """resume 接受 dict 或 dataclass（duck-type）。"""
        from dataclasses import dataclass

        @dataclass
        class SimpleResume:
            name: str
            phone: str
            email: str
            experience: List[Exp] = field(default_factory=list)

        r = SimpleResume(
            name="王五", phone="139", email="w@w.com",
            experience=[Exp(company="X", title="Y", description="Z" * 50, achievements=["A"])],
        )
        result = gen.generate_word(r, jd, template="conservative")
        assert "王五" in result.filename

    def test_estimate_returned(self, gen, minimal_resume, jd):
        """DocumentResult.estimate 含完整估算信息。"""
        result = gen.generate_word(minimal_resume, jd, template="conservative")
        e = result.estimate
        assert e.total_mm > 0
        assert e.capacity_mm == 265.0
        assert "header" in e.segment_lines

    def test_resume_accepts_resume_profile(self, gen, minimal_resume, jd):
        """ResumeProfile（Pydantic）也能直接传（duck-type via model_dump）。"""
        from models.resume import ResumeProfile

        r = ResumeProfile(
            name="赵六",
            phone="13800138000",
            email="z@z.com",
            target_roles=["测试"],
            experience=[{"company": "A", "title": "B", "description": "C" * 50, "achievements": ["D"]}],
        )
        result = gen.generate_word(r, jd, template="conservative")
        assert "赵六" in result.filename


# ============================================================
# PDF 生成（不走 playwright，因为 CI 可能没装 chromium 浏览器二进制）
# ============================================================

class TestGeneratePDFErrors:
    """PDF 生成只测错误路径（成功路径依赖 playwright chromium 二进制）。"""

    def test_overflow_strict_raises(self, gen, overflow_resume, jd):
        """超页 → OnePageOverflowError（不真调 playwright）。"""
        with pytest.raises(OnePageOverflowError):
            gen.generate_pdf(overflow_resume, jd, template="modern", strict_one_page=True)

    def test_filename_uses_pdf_ext(self, gen, minimal_resume, jd):
        """PDF 路径下文件名扩展是 .pdf。"""
        # 不真生成 PDF，只验证文件名逻辑
        # （避免依赖 playwright chromium）
        from services.document_generator import suggest_filename
        f = suggest_filename("张三", "PM", "字节", ext="pdf")
        assert f.endswith(".pdf")