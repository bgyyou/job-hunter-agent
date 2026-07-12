"""v3 M-rebuild-1: 一页纸预估器

按 update_plan.md §1.4 硬约束（10.5pt / 行距 1.2 / A4 可用区 265mm）
实时估算简历总高度，对比 A4 容量，给超页瘦身建议。

算法（中文字符优先）：
- 个人信息区：姓名 + 手机 + 邮箱 + 期望岗位 1 行（高 12mm）
- 段标题：每个 section 加粗一行（高 5mm）
- 文本行：字符数 / 30（含中英文混合）+ 换行 → 行数 → 行高 4.8mm
- 段额外行：每条 bullet 单独算行

输入：dict-like 或 ResumeProfile（duck typing 访问 .name / .experience /
.projects / .education / .skills / .achievements 即可）。
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PageEstimate:
    """一页纸预估结果。"""

    total_mm: float                          # 估算总高度 mm
    capacity_mm: float                       # A4 可用区 mm
    total_lines: int                         # 估算总行数（不计入标题/页边距）
    capacity_lines: int                      # 一页可容纳行数
    overflow: bool                           # 是否超页
    overflow_segments: List[str] = field(default_factory=list)  # 超页段名
    suggestions: List[str] = field(default_factory=list)         # 瘦身建议
    segment_lines: Dict[str, int] = field(default_factory=dict)  # 每段行数

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_mm": round(self.total_mm, 2),
            "capacity_mm": self.capacity_mm,
            "total_lines": self.total_lines,
            "capacity_lines": self.capacity_lines,
            "overflow": self.overflow,
            "overflow_segments": self.overflow_segments,
            "suggestions": self.suggestions,
            "segment_lines": self.segment_lines,
        }


class OnePageEstimator:
    """实时一页纸预估器。

    字号/排版硬约束按 update_plan.md §1.4：
    - 正文字号 10.5pt（中文 5 号字）
    - 行距 1.2
    - A4 可用区 265mm（高）x 182mm（宽）
    - 页边距 上下 12mm / 左右 14mm
    """

    # A4 可用区
    A4_USABLE_HEIGHT_MM = 265.0
    A4_USABLE_WIDTH_MM = 182.0

    # 行/段高（mm）
    LINE_HEIGHT_MM = 4.8        # 10.5pt + 1.2 行距
    HEADER_HEIGHT_MM = 12.0     # 个人信息区
    SECTION_TITLE_MM = 5.0      # 段标题加粗
    EDU_ROW_HEIGHT_MM = 4.5     # 教育背景行
    SKILL_ROW_HEIGHT_MM = 4.5   # 技能行
    PROJECT_DESC_MARGIN_MM = 1.5  # 段间小间距

    # 单行能容纳的字符数（10.5pt 中文约 30 字符/行）
    CHARS_PER_LINE = 30

    # 段优先级权重阈值（用于瘦身建议）
    GPA_LOW_THRESHOLD = 3.0
    SHORT_INTERNSHIP_MONTHS = 3
    REPEAT_SKILL_THRESHOLD = 3   # 同类技能 ≥ 3 个算重复

    def estimate(self, resume: Any, template: str = "conservative") -> PageEstimate:
        """估算简历总高度，对比 A4 容量。

        Args:
            resume: duck-typed 对象，需可访问以下字段：
                name, phone, email, target_roles/preferred_locations,
                skills, experience_years, education, projects, achievements,
                experience (嵌套 list)
            template: 模板名（保守/现代/创意），目前对容量影响一致。

        Returns:
            PageEstimate，含 overflow 标志 + 瘦身建议。
        """
        segment_lines: Dict[str, int] = {}
        overflow_segments: List[str] = []

        # 1. 个人信息区
        header_lines = self._header_lines(resume)
        header_mm = self.HEADER_HEIGHT_MM
        segment_lines["header"] = max(1, header_lines)

        # 2. 段标题累加（每个 section 5mm）
        section_count = 0

        # 3. 各 section 行数
        education_lines = self._education_lines(resume)
        segment_lines["education"] = education_lines
        if education_lines > 0:
            section_count += 1

        experience_lines = self._experience_lines(resume)
        segment_lines["experience"] = experience_lines
        if experience_lines > 0:
            section_count += 1

        projects_lines = self._project_lines(resume)
        segment_lines["projects"] = projects_lines
        if projects_lines > 0:
            section_count += 1

        skills_lines = self._skill_lines(resume)
        segment_lines["skills"] = skills_lines
        if skills_lines > 0:
            section_count += 1

        achievements_lines = self._achievement_lines(resume)
        segment_lines["achievements"] = achievements_lines
        if achievements_lines > 0:
            section_count += 1

        # 4. 行高累加
        total_lines = (
            segment_lines["header"]
            + segment_lines["education"]
            + segment_lines["experience"]
            + segment_lines["projects"]
            + segment_lines["skills"]
            + segment_lines["achievements"]
        )
        total_mm = (
            header_mm
            + section_count * self.SECTION_TITLE_MM
            + segment_lines["education"] * self.EDU_ROW_HEIGHT_MM
            + segment_lines["experience"] * self.LINE_HEIGHT_MM
            + segment_lines["projects"] * self.LINE_HEIGHT_MM
            + segment_lines["skills"] * self.SKILL_ROW_HEIGHT_MM
            + segment_lines["achievements"] * self.LINE_HEIGHT_MM
            + section_count * self.PROJECT_DESC_MARGIN_MM
        )

        capacity_lines = int(self.A4_USABLE_HEIGHT_MM / self.LINE_HEIGHT_MM)  # 约 55 行
        overflow = total_mm > self.A4_USABLE_HEIGHT_MM

        if overflow:
            # 找出超过比例最高的段
            ranked = sorted(
                segment_lines.items(),
                key=lambda kv: kv[1],
                reverse=True,
            )
            for seg_name, lines in ranked:
                if seg_name == "header":
                    continue
                if lines >= 3:
                    overflow_segments.append(seg_name)

        suggestions = self._build_suggestions(resume, overflow_segments) if overflow else []

        return PageEstimate(
            total_mm=round(total_mm, 2),
            capacity_mm=self.A4_USABLE_HEIGHT_MM,
            total_lines=total_lines,
            capacity_lines=capacity_lines,
            overflow=overflow,
            overflow_segments=overflow_segments,
            suggestions=suggestions,
            segment_lines=segment_lines,
        )

    # ---------------- helpers ----------------

    @staticmethod
    def _has_value(field: Any) -> bool:
        if field is None:
            return False
        if isinstance(field, (list, str, dict)) and len(field) == 0:
            return False
        return True

    def _header_lines(self, resume: Any) -> int:
        """个人信息区行数（≥1）。"""
        n_fields = sum(
            1
            for f in [getattr(resume, "name", None),
                     getattr(resume, "phone", None),
                     getattr(resume, "email", None),
                     getattr(resume, "target_roles", None),
                     getattr(resume, "preferred_locations", None)]
            if self._has_value(f)
        )
        return max(1, (n_fields + 1) // 2)  # 一行两字段

    def _education_lines(self, resume: Any) -> int:
        edu = getattr(resume, "education", []) or []
        return len(edu)

    def _experience_lines(self, resume: Any) -> int:
        """工作经历总行数：每段 = 1 行(标题) + description_chars/30 + achievements_count"""
        exp = getattr(resume, "experience", None)
        if exp is None:
            return 0
        total = 0
        for e in exp:
            desc = e.get("description", "") if isinstance(e, dict) else getattr(e, "description", "")
            achv = e.get("achievements", []) if isinstance(e, dict) else getattr(e, "achievements", []) or []
            desc_chars = len(desc or "")
            total += 1  # 标题行
            total += max(1, (desc_chars + self.CHARS_PER_LINE - 1) // self.CHARS_PER_LINE)
            total += len(achv)
        return total

    def _project_lines(self, resume: Any) -> int:
        proj = getattr(resume, "projects", None) or []
        total = 0
        for p in proj:
            desc = p.get("description", "") if isinstance(p, dict) else getattr(p, "description", "")
            achv = p.get("achievements", []) if isinstance(p, dict) else getattr(p, "achievements", []) or []
            desc_chars = len(desc or "")
            total += 1
            total += max(1, (desc_chars + self.CHARS_PER_LINE - 1) // self.CHARS_PER_LINE)
            total += len(achv)
        return total

    def _skill_lines(self, resume: Any) -> int:
        skills = getattr(resume, "skills", None) or []
        if isinstance(skills, dict):
            # 分类技能：technical/soft
            total_chars = sum(len(v) for v in skills.values() if isinstance(v, list))
        else:
            total_chars = len(skills)
        return max(1, (total_chars + 8) // 8)  # 一行 8 个技能

    def _achievement_lines(self, resume: Any) -> int:
        achv = getattr(resume, "achievements", None) or []
        return len(achv)

    def _build_suggestions(self, resume: Any, overflow_segments: List[str]) -> List[str]:
        """根据超页段给瘦身建议（按 update_plan.md §2.5）。"""
        suggestions: List[str] = []

        # GPA 偏低：建议删除
        edu = getattr(resume, "education", []) or []
        for e in edu:
            gpa = e.get("gpa") if isinstance(e, dict) else getattr(e, "gpa", None)
            if gpa is not None:
                try:
                    gpa_f = float(gpa)
                    if gpa_f < self.GPA_LOW_THRESHOLD:
                        suggestions.append(
                            f"GPA {gpa} 低于 {self.GPA_LOW_THRESHOLD}，建议删除 GPA 字段"
                        )
                        break
                except (ValueError, TypeError):
                    pass

        # 短期实习 < 3 月
        exp = getattr(resume, "experience", []) or []
        for e in exp:
            duration = e.get("duration") if isinstance(e, dict) else getattr(e, "duration", None)
            if duration and self._is_short_internship(duration):
                suggestions.append(
                    f"短期实习（{duration}）≤ {self.SHORT_INTERNSHIP_MONTHS} 月，建议合并或删除"
                )

        # 重复技能
        skills = getattr(resume, "skills", None) or []
        if isinstance(skills, list):
            counts = Counter(skills)
            repeats = {k: v for k, v in counts.items() if v >= self.REPEAT_SKILL_THRESHOLD}
            if repeats:
                suggestions.append(
                    f"重复技能 {list(repeats.keys())[:3]} 出现 ≥ {self.REPEAT_SKILL_THRESHOLD} 次，可去重"
                )

        if "experience" in overflow_segments:
            suggestions.append("工作经历段落总行数最多，建议精简描述 / 删除最早一段")
        if "projects" in overflow_segments:
            suggestions.append("项目经历段落总行数最多，建议只保留 2-3 个最相关的项目")
        if "achievements" in overflow_segments:
            suggestions.append("独立成果数据条目过多（>5 条），建议合并相似项")
        if not suggestions:
            suggestions.append("简历超出一页，建议精简整体内容")
        return suggestions

    @staticmethod
    def _is_short_internship(duration: str) -> bool:
        """判断是否为短期实习（< 3 月）。"""
        if not isinstance(duration, str):
            return False
        m = re.search(r"(\d+)\s*月", duration)
        if m:
            return int(m.group(1)) < 3
        return False