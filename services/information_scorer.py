"""v3 M-rebuild-2: 简历信息量评分 + 自动模式路由

按 update_plan.md §1.2 评估原简历"信息量" → 决定改写模式：

  ├─ 每段都有数据/细节 → 模式 A 改写
  ├─ 部分段落空/无数据 → 模式 A 改写 + 模式 B 补全
  └─ 基本空白 → 模式 B 全模板生成

评分维度（每段 0-100）：
- experience：每段 0-30（company/title/description/achievements 各 7.5 分，加成按段均）
- projects：每段 0-30
- education：每段 0-15（school/degree/major 时间齐全）
- achievements 顶层：0-15（按条数 5/3/2 分累计，上限 15）
- skills：0-10（按技能数量 2/2/3/3 上限 10）

阈值：
- total_score >= 70 → 模式 A
- 40 <= total_score < 70 → 模式 A+B
- total_score < 40 → 模式 B
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal


RecommendedMode = Literal["A", "A+B", "B"]


@dataclass
class InformationScore:
    """信息量评分结果。"""

    total_score: float                                # 0-100
    experience_completeness: float = 0.0              # 0-100（experience 段加权）
    projects_completeness: float = 0.0                # 0-100
    education_completeness: float = 0.0               # 0-100
    achievements_completeness: float = 0.0            # 0-100
    skills_completeness: float = 0.0                  # 0-100
    recommended_mode: RecommendedMode = "A"
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_score": round(self.total_score, 2),
            "experience_completeness": round(self.experience_completeness, 2),
            "projects_completeness": round(self.projects_completeness, 2),
            "education_completeness": round(self.education_completeness, 2),
            "achievements_completeness": round(self.achievements_completeness, 2),
            "skills_completeness": round(self.skills_completeness, 2),
            "recommended_mode": self.recommended_mode,
            "reason": self.reason,
        }


class InformationScorer:
    """简历信息量评分器。"""

    # 阈值
    THRESHOLD_A = 70.0       # >= 70 走模式 A
    THRESHOLD_A_B = 40.0     # 40-69 走 A+B

    # 段满分
    EXPERIENCE_MAX_PER_SEG = 30.0
    PROJECTS_MAX_PER_SEG = 30.0
    EDUCATION_MAX_PER_SEG = 15.0
    ACHIEVEMENTS_MAX = 15.0
    SKILLS_MAX = 10.0

    # 每字段满分
    FIELD_PER_ATTR = 7.5     # experience / projects 段每字段 7.5

    def score(self, resume: Any) -> InformationScore:
        """对简历打分，返回 InformationScore（含 recommended_mode）。"""
        resume_d = resume if isinstance(resume, dict) else _attr_to_dict(resume)

        experience_score = self._score_experience(resume_d.get("experience") or [])
        projects_score = self._score_projects(resume_d.get("projects") or [])
        education_score = self._score_education(resume_d.get("education") or [])
        achievements_score = self._score_achievements(resume_d.get("achievements") or [])
        skills_score = self._score_skills(resume_d.get("skills") or [])

        # 加权平均：experience 权重最高
        total = (
            experience_score * 0.35
            + projects_score * 0.25
            + education_score * 0.15
            + achievements_score * 0.15
            + skills_score * 0.10
        )

        # 决定推荐模式
        if total >= self.THRESHOLD_A:
            mode: RecommendedMode = "A"
            reason = f"信息量充足（{total:.1f} 分 ≥ 70），适合模式 A 视角切换"
        elif total >= self.THRESHOLD_A_B:
            mode = "A+B"
            reason = (
                f"信息量部分充足（{total:.1f} 分在 40-69 之间），"
                "适合模式 A 改写 + 模式 B 补全空段"
            )
        else:
            mode = "B"
            reason = f"信息量偏少（{total:.1f} 分 < 40），适合模式 B 全模板生成"

        return InformationScore(
            total_score=round(total, 2),
            experience_completeness=experience_score,
            projects_completeness=projects_score,
            education_completeness=education_score,
            achievements_completeness=achievements_score,
            skills_completeness=skills_score,
            recommended_mode=mode,
            reason=reason,
        )

    # ---------------- segment scoring ----------------

    def _score_experience(self, experience: List[Any]) -> float:
        if not experience:
            return 0.0
        per_seg_total = 0.0
        for exp in experience:
            seg_score = 0.0
            if isinstance(exp, dict):
                if exp.get("company"):
                    seg_score += self.FIELD_PER_ATTR
                if exp.get("title"):
                    seg_score += self.FIELD_PER_ATTR
                if exp.get("description") and len(exp["description"]) >= 30:
                    seg_score += self.FIELD_PER_ATTR
                achv = exp.get("achievements") or []
                if achv:
                    seg_score += self.FIELD_PER_ATTR
            per_seg_total += min(seg_score, self.EXPERIENCE_MAX_PER_SEG)
        # 至少 1 段满 70% 算合格（按段数归一化）
        max_total = len(experience) * self.EXPERIENCE_MAX_PER_SEG
        if max_total == 0:
            return 0.0
        return (per_seg_total / max_total) * 100.0

    def _score_projects(self, projects: List[Any]) -> float:
        if not projects:
            return 0.0
        per_seg_total = 0.0
        for proj in projects:
            seg_score = 0.0
            if isinstance(proj, dict):
                if proj.get("name"):
                    seg_score += self.FIELD_PER_ATTR
                if proj.get("role"):
                    seg_score += self.FIELD_PER_ATTR
                if proj.get("description") and len(proj["description"]) >= 20:
                    seg_score += self.FIELD_PER_ATTR
                achv = proj.get("achievements") or []
                if achv:
                    seg_score += self.FIELD_PER_ATTR
            per_seg_total += min(seg_score, self.PROJECTS_MAX_PER_SEG)
        max_total = len(projects) * self.PROJECTS_MAX_PER_SEG
        return (per_seg_total / max_total) * 100.0 if max_total > 0 else 0.0

    def _score_education(self, education: List[Any]) -> float:
        if not education:
            return 0.0
        per_seg_total = 0.0
        for edu in education:
            seg_score = 0.0
            if isinstance(edu, dict):
                if edu.get("school"):
                    seg_score += 5
                if edu.get("degree"):
                    seg_score += 4
                if edu.get("major"):
                    seg_score += 3
                if edu.get("start_year") and edu.get("end_year"):
                    seg_score += 3
            per_seg_total += min(seg_score, self.EDUCATION_MAX_PER_SEG)
        max_total = len(education) * self.EDUCATION_MAX_PER_SEG
        return (per_seg_total / max_total) * 100.0 if max_total > 0 else 0.0

    def _score_achievements(self, achievements: List[str]) -> float:
        """独立成果数据条目加分：≥4 条满分。"""
        n = len(achievements)
        if n >= 4:
            return 100.0
        if n == 3:
            return 75.0
        if n == 2:
            return 50.0
        if n == 1:
            return 25.0
        return 0.0

    def _score_skills(self, skills: Any) -> float:
        """技能评分：≥5 个满分。"""
        if isinstance(skills, dict):
            n = sum(len(v) for v in skills.values() if isinstance(v, list))
        elif isinstance(skills, list):
            n = len(skills)
        else:
            return 0.0
        if n >= 5:
            return 100.0
        return min(n * 20.0, 100.0)


# ============================================================
# Duck-type helper
# ============================================================

def _attr_to_dict(obj: Any) -> Dict[str, Any]:
    """把 ResumeProfile / StructuredJD 等转 dict。"""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "__dict__"):
        return vars(obj)
    return {}