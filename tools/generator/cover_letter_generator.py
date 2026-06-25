# tools/generator/cover_letter_generator.py
"""
Cover Letter 生成器 - 根据简历和 JD 生成针对性求职信
"""
from typing import Dict, Any
from loguru import logger
from tools.llm import LLMClient, LLMMessage


class CoverLetterGenerator:
    """Cover Letter 生成器"""

    def __init__(self, llm_client: LLMClient):
        """
        初始化 Cover Letter 生成器

        Args:
            llm_client: LLM 客户端
        """
        self.llm_client = llm_client
        self.logger = logger.bind(component="cover_letter_generator")

    async def generate(
        self,
        resume_data: Dict[str, Any],
        job_profile: Dict[str, Any],
        company_name: str
    ) -> str:
        """
        生成 Cover Letter

        Args:
            resume_data: 简历数据
            job_profile: 职位信息
            company_name: 公司名称

        Returns:
            Cover Letter 文本
        """
        self.logger.info(f"开始生成 {company_name} 的 Cover Letter")

        prompt = self._build_prompt(resume_data, job_profile, company_name)

        messages = [LLMMessage(role="user", content=prompt)]

        response = await self.llm_client.analyze(
            messages=messages,
            temperature=0.8  # 稍高温度增加自然感
        )

        return response.content.strip()

    def _build_prompt(
        self,
        resume_data: Dict[str, Any],
        job_profile: Dict[str, Any],
        company_name: str
    ) -> str:
        """构建 Prompt"""

        # 格式化候选人信息
        header = resume_data.get("header", {})
        name = header.get("name", "")
        email = header.get("contact", {}).get("email", "")
        summary = header.get("summary", "")

        # 格式化工作经历
        experience_text = self._format_experience(resume_data.get("experience", []))

        # 格式化项目经历
        projects_text = self._format_projects(resume_data.get("projects", []))

        # 格式化技能
        skills = resume_data.get("skills", {})
        if isinstance(skills, dict):
            skills_text = ", ".join(skills.get("technical", []))
        elif isinstance(skills, list):
            skills_text = ", ".join(str(skill) for skill in skills)
        else:
            skills_text = str(skills or "")

        # 格式化职位信息
        job_title = job_profile.get("title", "")
        job_company = job_profile.get("company", company_name)
        core_requirements = "\n".join(
            f"- {req}" for req in job_profile.get("core_requirements", [])[:5]
        )

        # 格式化隐性要求
        implicit_requirements = job_profile.get("implicit_requirements", "")

        prompt = f"""根据以下简历和职位描述，生成一封专业的求职信。

## 候选人信息
**姓名：** {name}
**联系方式：** {email}
**个人陈述：** {summary}

## 候选人经验
**工作经历：**
{experience_text}

**项目经历：**
{projects_text}

**技能：** {skills_text}

## 目标职位
**职位名称：** {job_title}
**公司：** {job_company}
**地点：** {job_profile.get('location', '未知')}
**薪资：** {job_profile.get('salary_range', '面议')}

## 职位要求
**核心要求：**
{core_requirements if core_requirements else '见职位描述'}

**隐性要求分析：**
{implicit_requirements if implicit_requirements else '无明显隐性要求'}

## 求职信要求

1. **开头：** 说明申请职位和来源（如：在 Boss 直聘上看到的）
2. **中间：** 强调与职位相关的经验和能力（2-3 点具体内容）
3. **结尾：** 表达兴趣并请求面试
4. **语气：** 专业、真诚、不夸大
5. **长度：** 200-300 字（中文）
6. **针对性：** 内容要与目标职位高度相关，不使用模板化语言

请生成求职信（只返回求职信内容，不要有其他说明）："""

        return prompt

    def _format_experience(self, experience: list) -> str:
        """格式化工作经历"""
        if not experience:
            return "暂无"

        lines = []
        for exp in experience[:3]:  # 只取前 3 个
            title = exp.get("title", "")
            company = exp.get("company", "")
            description = exp.get("description", "")[:50]

            if title and company:
                lines.append(f"- {title} @ {company}：{description}...")

        return "\n".join(lines) if lines else "暂无"

    def _format_projects(self, projects: list) -> str:
        """格式化项目经历"""
        if not projects:
            return "暂无"

        lines = []
        for proj in projects[:3]:  # 只取前 3 个
            name = proj.get("name", "")
            description = proj.get("description", "")[:50]

            if name:
                lines.append(f"- {name}：{description}...")

        return "\n".join(lines) if lines else "暂无"

    def format_cover_letter(self, cover_letter: str, name: str, date: str = None) -> str:
        """
        格式化 Cover Letter

        Args:
            cover_letter: Cover Letter 内容
            name: 候选人姓名
            date: 日期（默认今天）

        Returns:
            格式化后的 Cover Letter
        """
        from datetime import datetime

        if date is None:
            date = datetime.now().strftime("%Y年%m月%d日")

        formatted = f"""
# 求职信

**日期：** {date}
**申请人：** {name}

---

{cover_letter}

---

祝好！

{name}
"""

        return formatted.strip()

    async def generate_and_format(
        self,
        resume_data: Dict[str, Any],
        job_profile: Dict[str, Any],
        company_name: str
    ) -> str:
        """
        生成并格式化 Cover Letter

        Args:
            resume_data: 简历数据
            job_profile: 职位信息
            company_name: 公司名称

        Returns:
            格式化后的 Cover Letter
        """
        name = resume_data.get("header", {}).get("name", "")

        cover_letter = await self.generate(resume_data, job_profile, company_name)

        return self.format_cover_letter(cover_letter, name)