"""v3 M-rebuild-2: 信息量评分器测试

覆盖评分边界值（极简/部分/完整）+ 自动路由推荐模式正确性。
"""
import pytest

from services.information_scorer import InformationScorer


@pytest.fixture
def scorer():
    return InformationScorer()


class TestInformationScorer:
    """信息量评分器单元测试。"""

    def test_empty_resume_score_zero(self, scorer):
        """完全空简历 → total=0 → 推荐 mode=B。"""
        score = scorer.score({})
        assert score.total_score == 0.0
        assert score.recommended_mode == "B"
        assert "偏少" in score.reason

    def test_minimal_resume_score_below_40(self, scorer):
        """极简简历（只有姓名 + 1 段空 experience）→ mode=B。"""
        resume = {
            "name": "张三",
            "experience": [{"company": "", "title": "", "description": "", "achievements": []}],
            "achievements": [],
            "skills": [],
        }
        score = scorer.score(resume)
        assert score.total_score < 40.0
        assert score.recommended_mode == "B"

    def test_partial_resume_score_between_40_70(self, scorer):
        """部分信息（1 段有内容 + 空 projects + 完整 education + 2 skills）→ mode=A+B。"""
        resume = {
            "experience": [
                {
                    "company": "字节跳动",
                    "title": "产品经理",
                    "description": "负责 AI 产品规划" * 5,
                    "achievements": ["促成 200 单成交", "GMV 120 万", "DAU 增长 30%"],
                }
            ],
            "projects": [],
            "education": [
                {"school": "北大", "degree": "本科", "major": "CS", "start_year": 2018, "end_year": 2022}
            ],
            "achievements": ["促成 200 单成交", "GMV 120 万"],
            "skills": ["Python", "SQL", "产品规划"],
        }
        score = scorer.score(resume)
        assert 40.0 <= score.total_score < 70.0
        assert score.recommended_mode == "A+B"

    def test_full_resume_score_above_70(self, scorer):
        """完整简历（2 段 experience + 1 项目 + education + 4 achievements + 5 skills）→ mode=A。"""
        resume = {
            "experience": [
                {
                    "company": "字节跳动",
                    "title": "产品经理",
                    "description": "负责 AI 产品规划" * 10,
                    "achievements": ["促成 200 单成交", "GMV 120 万"],
                },
                {
                    "company": "腾讯",
                    "title": "高级产品",
                    "description": "负责微信小程序产品" * 10,
                    "achievements": ["DAU 增长 30%"],
                },
            ],
            "projects": [
                {
                    "name": "AI Agent 平台",
                    "role": "PM",
                    "description": "设计 prompt 工程平台" * 5,
                    "achievements": ["日活 1万+"],
                }
            ],
            "education": [
                {"school": "北大", "degree": "本科", "major": "CS", "start_year": 2018, "end_year": 2022}
            ],
            "achievements": ["A", "B", "C", "D"],
            "skills": ["Python", "SQL", "产品规划", "数据分析", "AI"],
        }
        score = scorer.score(resume)
        assert score.total_score >= 70.0
        assert score.recommended_mode == "A"
        assert score.experience_completeness >= 80.0
        assert score.projects_completeness >= 80.0

    def test_to_dict_serialization(self, scorer):
        """score.to_dict() 返回所有字段。"""
        score = scorer.score({})
        d = score.to_dict()
        assert "total_score" in d
        assert "recommended_mode" in d
        assert "reason" in d
        assert d["recommended_mode"] == "B"


class TestScorerThresholds:
    """阈值边界测试（THRESHOLD_A=70 / THRESHOLD_A_B=40）。"""

    def test_threshold_a_value(self, scorer):
        assert scorer.THRESHOLD_A == 70.0

    def test_threshold_a_b_value(self, scorer):
        assert scorer.THRESHOLD_A_B == 40.0

    def test_score_is_deterministic(self, scorer):
        """相同输入应返回相同分数。"""
        resume = {
            "experience": [
                {"company": "X", "title": "Y", "description": "Z" * 50, "achievements": ["a"]}
            ]
        }
        s1 = scorer.score(resume)
        s2 = scorer.score(resume)
        assert s1.total_score == s2.total_score