"""v3 M-rebuild-1: 一页纸预估器测试

覆盖基本情况 + 超页边界 + 段优先级权重（GPA / 短期实习 / 重复技能）。
"""
import pytest
from dataclasses import dataclass, field
from typing import List

from services.one_page_estimator import OnePageEstimator, PageEstimate


@dataclass
class Edu:
    school: str
    degree: str
    major: str
    start_year: int
    end_year: int
    gpa: float = None


@dataclass
class Exp:
    company: str
    title: str
    duration: str
    description: str
    achievements: list = field(default_factory=list)


@dataclass
class Proj:
    name: str
    role: str
    description: str
    achievements: list = field(default_factory=list)


@dataclass
class Resume:
    name: str = ""
    phone: str = ""
    email: str = ""
    target_roles: List[str] = field(default_factory=list)
    skills: List[str] = field(default_factory=list)
    education: List[Edu] = field(default_factory=list)
    experience: List[Exp] = field(default_factory=list)
    projects: List[Proj] = field(default_factory=list)
    achievements: List[str] = field(default_factory=list)


@pytest.fixture
def estimator():
    return OnePageEstimator()


class TestOnePageEstimator:
    """一页纸预估器单元测试。"""

    def test_minimal_resume_fits_one_page(self, estimator):
        """极简简历（1 段 experience）→ 不超页。"""
        r = Resume(
            name="张三",
            phone="13800138000",
            email="zhangsan@example.com",
            target_roles=["Python 工程师"],
            skills=["Python"],
            education=[Edu(school="北大", degree="本科", major="CS", start_year=2018, end_year=2022)],
            experience=[Exp(company="字节跳动", title="Python 开发", duration="12月",
                            description="负责后端开发", achievements=["促成 200 单成交"])],
        )
        estimate = estimator.estimate(r)
        assert isinstance(estimate, PageEstimate)
        assert estimate.overflow is False
        assert estimate.total_mm <= estimator.A4_USABLE_HEIGHT_MM

    def test_overflow_resume_detected(self, estimator):
        """大量内容简历 → 触发 overflow。"""
        r = Resume(
            name="张三",
            phone="13800138000",
            email="zhangsan@example.com",
            target_roles=["Python", "AI"],
            skills=["Python", "Django", "PG", "Redis", "Docker", "K8s", "AWS", "MongoDB"],
            education=[Edu(school="北大", degree="本科", major="CS", start_year=2018, end_year=2022)],
            experience=[
                Exp(company="字节跳动", title="PM", duration="12月",
                    description="负责后端" * 200, achievements=["a"] * 10),
                Exp(company="美团", title="PM", duration="24月",
                    description="负责设计" * 150, achievements=["b"] * 10),
                Exp(company="小红书", title="架构师", duration="36月",
                    description="负责架构" * 150, achievements=["c"] * 10),
            ],
            achievements=["A", "B", "C", "D", "E", "F"],
        )
        estimate = estimator.estimate(r)
        assert estimate.overflow is True
        assert "experience" in estimate.overflow_segments or "achievements" in estimate.overflow_segments
        assert len(estimate.suggestions) > 0

    def test_low_gpa_suggestion(self, estimator):
        """GPA < 3.0 触发删除建议。"""
        r = Resume(
            name="张三", phone="138", email="z@s.com",
            education=[Edu(school="北大", degree="本科", major="CS", start_year=2018, end_year=2022, gpa=2.5)],
        )
        # 制造超页
        r.experience = [
            Exp(company=f"C{i}", title="T", duration="12月", description="x" * 300, achievements=["a"] * 8)
            for i in range(5)
        ]
        estimate = estimator.estimate(r)
        assert estimate.overflow is True
        assert any("GPA" in s for s in estimate.suggestions)

    def test_short_internship_suggestion(self, estimator):
        """短期实习（< 3 月）触发合并建议。"""
        r = Resume(
            name="张三", phone="138", email="z@s.com",
            education=[Edu(school="北大", degree="本科", major="CS", start_year=2018, end_year=2022)],
            experience=[Exp(company="字节跳动", title="实习", duration="2月", description="打杂")],
        )
        r.experience += [
            Exp(company=f"C{i}", title="T", duration="12月", description="x" * 300, achievements=["a"] * 8)
            for i in range(4)
        ]
        estimate = estimator.estimate(r)
        assert estimate.overflow is True
        assert any("短期实习" in s for s in estimate.suggestions)

    def test_repeat_skills_suggestion(self, estimator):
        """重复技能 ≥ 3 次触发去重建议。"""
        r = Resume(
            name="张三", phone="138", email="z@s.com",
            skills=["Python"] * 5,  # 5 次 Python 重复
            experience=[
                Exp(company="字节跳动", title="PM", duration="12月",
                    description="x" * 300, achievements=["a"] * 8)
                for _ in range(4)
            ],
        )
        estimate = estimator.estimate(r)
        assert estimate.overflow is True
        assert any("重复技能" in s for s in estimate.suggestions)

    def test_segment_lines_tracked(self, estimator):
        """每段行数被记录在 segment_lines。"""
        r = Resume(
            name="张三", phone="138", email="z@s.com",
            experience=[Exp(company="X", title="T", duration="12月", description="y" * 60, achievements=["a", "b"])],
        )
        estimate = estimator.estimate(r)
        assert "header" in estimate.segment_lines
        assert "experience" in estimate.segment_lines
        assert estimate.segment_lines["experience"] > 0

    def test_to_dict_serialization(self, estimator):
        """estimate.to_dict() 返回完整字典。"""
        r = Resume(name="张三", phone="138", email="z@s.com")
        d = estimator.estimate(r).to_dict()
        assert "total_mm" in d
        assert "capacity_mm" in d
        assert "overflow" in d
        assert d["capacity_mm"] == 265.0