"""v3 M-rebuild-2: 改写服务 LLM prompt 锁死

按 update_plan.md §2.4：模式 A（基于原简历改写）+ 模式 B（生成无公司名模板）。

**严禁修改这些 prompt 的核心约束**——它们是 v3 防止 LLM 编造数据的最后一道防线。
如需调整请同时更新 update_plan.md §2.4 + 加测试断言。
"""

from __future__ import annotations

from typing import Any, Dict


# ============================================================
# 模式 A：基于原简历改写（视角切换 + 数字保留）
# ============================================================

MODE_A_SYSTEM_PROMPT = """你是一位资深求职简历顾问，擅长把已有工作经历"重新诠释"为目标岗位视角。

# Hard Rules（绝对不能违反）
1. 绝对不能编造原简历中没有的数据、数字、奖项
2. 保留所有数字、人名、公司名、时间不变
3. 把每段经历从"做了什么"改成"带来了什么"（结果导向）
4. 改写后每段附一句"改写思路"
5. 如果原简历某段实在无法对接目标 JD，明确说"建议删除或大改"
6. 涉及百分比/增长率时，只能用"显著/明显/约"等模糊词，不能用具体数字（除非原简历有）

# Output Format
{
  "rewrites": [
    {
      "original": "原段落原文",
      "rewritten": "改写后内容",
      "rewrite_reason": "为什么这么改，对接了 JD 中哪个能力词",
      "warning": "如有风险点必填（如编造嫌疑 / 建议删除）"
    }
  ]
}
"""


def build_mode_a_user_prompt(original: Dict[str, Any], jd: Dict[str, Any]) -> str:
    """Build the user prompt for Mode A rewrite.

    Args:
        original: 原简历 dict（含 experience / projects / education / achievements）。
        jd: StructuredJD 字典（含 responsibilities / requirements）。
    """
    jd_summary = (
        f"目标岗位：{jd.get('title') or '未知'}\n"
        f"公司：{jd.get('company') or '未知'}\n"
        f"行业：{jd.get('industry') or '未知'}\n"
        f"职能：{jd.get('function') or '未知'}\n"
        f"级别：{jd.get('level') or '未知'}\n"
    )
    if jd.get("responsibilities"):
        jd_summary += "职责：\n" + "\n".join(f"- {r}" for r in jd["responsibilities"]) + "\n"
    if jd.get("requirements"):
        jd_summary += "要求：\n" + "\n".join(f"- {r}" for r in jd["requirements"]) + "\n"

    resume_summary = "原简历要点：\n"
    experience = original.get("experience") or []
    if experience:
        resume_summary += "工作经历：\n"
        for i, exp in enumerate(experience, 1):
            if isinstance(exp, dict):
                resume_summary += (
                    f"{i}. {exp.get('company', '未知公司')} / "
                    f"{exp.get('title', '未知岗位')} / "
                    f"{exp.get('start_date', '?')}-{exp.get('end_date', '?')}\n"
                    f"   描述：{exp.get('description', '')}\n"
                )
                achv = exp.get("achievements") or []
                if achv:
                    resume_summary += "   成果：\n"
                    for a in achv:
                        resume_summary += f"   - {a}\n"

    projects = original.get("projects") or []
    if projects:
        resume_summary += "\n项目经历：\n"
        for i, p in enumerate(projects, 1):
            if isinstance(p, dict):
                resume_summary += (
                    f"{i}. {p.get('name', '未知项目')} / "
                    f"角色：{p.get('role', '未知')} / "
                    f"时间：{p.get('start_date', '?')}-{p.get('end_date', '?')}\n"
                    f"   描述：{p.get('description', '')}\n"
                )

    achievements = original.get("achievements") or []
    if achievements:
        resume_summary += "\n独立成果：\n" + "\n".join(f"- {a}" for a in achievements) + "\n"

    return (
        "请基于以下原简历，按目标 JD 视角进行改写。\n\n"
        f"=== 目标 JD ===\n{jd_summary}\n"
        f"=== 原简历 ===\n{resume_summary}\n\n"
        "请按 system prompt 的输出格式返回 JSON。"
    )


# ============================================================
# 模式 B：生成"无公司名/时间/学校"的模板
# ============================================================

MODE_B_SYSTEM_PROMPT = """你是资深求职简历顾问，为目标岗位生成"参考模板"。

# Hard Rules（绝对不能违反）
1. 绝对不能编造公司名、学校名、项目名
2. 绝对不能编造具体时间
3. 数字用范围/区间（如"月均获客 500-1000"），不用精确数
4. 每段输出末尾必须标注"[AI 模板生成]"
5. 内容只针对"目标 JD 中的能力关键词"，不绑定任何具体行业经历

# Output Format
{
  "templates": [
    {
      "section": "工作经历 / 项目经历",
      "content": "...",
      "anchored_keywords": ["JD 中的能力词 1", "能力词 2"],
      "is_ai_generated": true
    }
  ]
}
"""


def build_mode_b_user_prompt(jd: Dict[str, Any],
                             sections: list = None) -> str:
    """Build the user prompt for Mode B template generation."""
    sections = sections or ["experience", "projects"]

    jd_summary = (
        f"目标岗位：{jd.get('title') or '通用岗位'}\n"
        f"行业：{jd.get('industry') or '通用'}\n"
        f"职能：{jd.get('function') or '通用'}\n"
        f"级别：{jd.get('level') or '通用'}\n"
    )
    if jd.get("responsibilities"):
        jd_summary += "职责关键词：\n" + "\n".join(f"- {r}" for r in jd["responsibilities"]) + "\n"
    if jd.get("requirements"):
        jd_summary += "能力要求：\n" + "\n".join(f"- {r}" for r in jd["requirements"]) + "\n"

    section_text = "、".join(sections)

    return (
        f"请为以下目标岗位生成 {section_text} 段落的「参考模板」。\n\n"
        f"=== 目标 JD ===\n{jd_summary}\n\n"
        "要求：\n"
        "- 不编造任何公司名 / 学校名 / 项目名 / 具体时间\n"
        "- 数字用范围/区间，不用精确数\n"
        "- 每段末尾标注 [AI 模板生成]\n"
        "- 每段 anchored_keywords 列出对接的 JD 能力词\n\n"
        "请按 system prompt 的输出格式返回 JSON。"
    )


# ============================================================
# 模式 A+B：混合（模式 A 为主 + 模式 B 补全空段）
# ============================================================

MODE_AB_SYSTEM_PROMPT = """你是一位资深求职简历顾问。本次任务是把已有简历按目标 JD 改写 + 对缺失段落用模板补全。

# Hard Rules（绝对不能违反）
1. 已有段落按"模式 A 改写"约束：保留所有数字/人名/时间
2. 新增段落按"模式 B 模板"约束：不编造公司名/时间/学校，数字用区间
3. 已有段落不要凭空添加新事实；新增段落末尾必须标注"[AI 模板生成]"
4. 改写后的整体结构对齐目标 JD 的能力词顺序

# Output Format
{
  "rewrites": [
    {
      "section": "experience / projects / achievements",
      "mode": "A 或 B",
      "original": "原段落原文（模式 B 填 null）",
      "rewritten": "改写/补全后内容",
      "rewrite_reason": "为什么这么改",
      "anchored_keywords": ["JD 能力词"],
      "warning": "如有风险点必填"
    }
  ]
}
"""