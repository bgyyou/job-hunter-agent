#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简历解析器 - 智能解析器，支持中英文简历

支持格式：
1. 英文简历：Company | Title (一行), Date | Location (另一行)
2. 中文简历：时间-公司-职位 (分行)
3. 多种技能格式：Core Competencies, 个人优势, etc.
"""

import re
import json
import pymupdf
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from loguru import logger

# v2.1 M2.5: LLM 抽取支持（可选依赖；无 LLM client 时降级到正则）
try:
    from tools.llm import LLMClient, LLMMessage
except Exception:
    LLMClient = None  # type: ignore
    LLMMessage = None  # type: ignore


@dataclass
class ResumeData:
    """简历数据结构"""
    header: Dict[str, Any]
    experience: List[Dict[str, Any]]
    projects: List[Dict[str, Any]]
    skills: Dict[str, List[str]]
    education: List[Dict[str, Any]]
    validation: Dict[str, Any]


class ResumeParser:
    """智能简历解析器"""

    # 章节识别关键词
    SECTION_KEYWORDS = {
        'experience': [
            'work experience', 'work history', 'professional experience', 'employment',
            '工作经历', '工作经验', '职业经历', 'employment history', 'career history'
        ],
        'projects': [
            'projects', 'project experience', 'key projects', 'ai projects',
            '项目经验', '项目经历', 'project highlights', 'notable projects'
        ],
        'skills': [
            'skills', 'core competencies', 'technical skills', 'competencies',
            '技能', '个人优势', '专业技能', 'competencies', 'skill summary'
        ],
        'education': [
            'education', 'educational background', 'academic background',
            '教育经历', '教育背景', '学历', 'academic experience'
        ]
    }

    # 技能关键词（用于提取）
    TECH_SKILL_KEYWORDS = [
        'Python', 'Java', 'JavaScript', 'TypeScript', 'React', 'Vue', 'Angular',
        'Node.js', 'Express', 'FastAPI', 'Django', 'Flask', 'Spring',
        'Supabase', 'PostgreSQL', 'MySQL', 'MongoDB', 'Redis',
        'SQL', 'REST', 'GraphQL', 'API', 'Docker', 'Kubernetes',
        'AWS', 'Azure', 'GCP', 'Google Cloud', 'Azure',
        'Claude', 'OpenAI', 'GPT', 'ChatGPT', 'LLM', 'AI', 'ML',
        'Pandas', 'NumPy', 'Scikit-learn', 'TensorFlow', 'PyTorch',
        'Git', 'GitHub', 'GitLab', 'CI/CD', 'DevOps',
        'Web Scraping', 'Automation', 'Data Analysis',
        'SEO', 'SEM', 'Digital Marketing', 'Content Marketing',
        '小红书', '抖音', '视频号', '公众号', 'WeChat', 'LinkedIn',
        'Canvas', 'Office', 'Excel', 'PowerPoint', 'Word',
        '数据分析', '广告投放', '营销策划', '内容运营', '品牌推广'
    ]

    SOFT_SKILL_KEYWORDS = [
        'leadership', 'teamwork', 'communication', 'problem-solving',
        'adaptability', 'innovation', 'creativity', 'analytical',
        'leadership', 'management', 'project management',
        '领导力', '团队合作', '沟通', '问题解决', '创新', '快速学习',
        '体系构建', '文案写作', '学习能力', '组织能力'
    ]

    def __init__(self, llm_client: Optional["LLMClient"] = None):
        """初始化解析器

        Args:
            llm_client: 可选的 LLM 客户端。传入则优先用 LLM 做结构化抽取，失败时降级到正则；
                       未传入则直接走正则路径（兼容旧调用方）。
        """
        self.llm_client = llm_client
        # 不再让 parser 自己加 logger sink — 由 config.settings.setup_logging() 统一管理（v2.1 M1）

    async def parse(self, pdf_path: str) -> Dict[str, Any]:
        """
        解析 PDF 简历

        Args:
            pdf_path: PDF 文件路径

        Returns:
            解析后的简历数据字典
        """
        logger.info(f"开始解析简历: {pdf_path}")

        # 提取文本
        text = self._extract_text(pdf_path)

        # v2.1 M2.5: 优先走 LLM 路径，失败降级到正则
        if self.llm_client is not None:
            try:
                result = await self._parse_with_llm(text)
                header = result.get("header", {})
                logger.info(
                    f"[LLM] 解析完成: 姓名={header.get('name', 'Unknown')}, "
                    f"经历={len(result.get('experience', []))}条, "
                    f"项目={len(result.get('projects', []))}条"
                )
                return result
            except Exception as e:
                logger.warning(f"LLM 抽取失败，降级到正则解析: {e}")

        return self._parse_with_regex(text)

    def _parse_with_regex(self, text: str) -> Dict[str, Any]:
        """正则解析路径（旧逻辑，作为 LLM 失败时的兜底）"""
        lines = [line.strip() for line in text.split('\n') if line.strip()]

        sections = self._identify_sections(lines)
        header = self._parse_header(lines, text)
        experience = self._parse_experience(lines, sections)
        projects = self._parse_projects(lines, sections)
        skills = self._parse_skills(lines, sections, text)
        education = self._parse_education(lines, sections)
        validation = self._validate_completeness(header, experience, skills, education)

        result = {
            "header": header,
            "experience": experience,
            "projects": projects,
            "skills": skills,
            "education": education,
            "validation": validation,
        }
        logger.info(
            f"[Regex] 解析完成: 姓名={header.get('name', 'Unknown')}, "
            f"经历={len(experience)}条, 项目={len(projects)}条"
        )
        return result

    async def _parse_with_llm(self, text: str) -> Dict[str, Any]:
        """LLM 结构化抽取路径"""
        if LLMMessage is None:
            raise RuntimeError("LLMMessage 不可用（tools.llm 未加载）")

        schema = {
            "header": {
                "name": "姓名",
                "contact": {"phone": "电话（原文保留）", "email": "邮箱"},
                "summary": "个人简介/自我评价（不超过 300 字）",
            },
            "experience": [
                {
                    "company": "公司全称",
                    "title": "职位",
                    "start_date": "开始时间（如 2022.07 / Jul 2022）",
                    "end_date": "结束时间（在职填'至今'/'Present'）",
                    "location": "工作地点（无则 null）",
                    "description": "工作内容/职责描述，把所有 bullet 用换行连起来，保留原文细节",
                }
            ],
            "projects": [
                {
                    "name": "项目名",
                    "description": "项目描述",
                    "role": "项目角色（无则 null）",
                    "tech_stack": ["技术栈1", "技术栈2"],
                }
            ],
            "skills": {
                "technical": ["硬技能1", "硬技能2"],
                "soft": ["软技能1", "软技能2"],
            },
            "education": [
                {
                    "school": "学校",
                    "degree": "学位（如 硕士 / Master）",
                    "major": "专业",
                    "start_date": "开始时间",
                    "end_date": "结束时间",
                    "location": "地点（无则 null）",
                    "gpa": "GPA（无则 null）",
                }
            ],
        }

        prompt = (
            "你是简历解析助手。下面是一份简历的纯文本（来自 PDF 文本提取，可能格式不规整）。\n"
            "请把简历内容**完整**抽取为结构化 JSON。注意：\n"
            "1. experience.description 必须包含**所有** bullet 点的内容，按行用 \\n 分隔，不要遗漏任何一条职责；\n"
            "2. 中英文混排时按原文保留，不要翻译；\n"
            "3. skills.technical 收录所有出现过的技术/工具/平台名词（包括中文），不要漏；\n"
            "4. 找不到的字段填 null 或空数组，不要瞎编；\n"
            "5. 时间格式按原文。\n\n"
            "简历正文：\n"
            "===\n"
            f"{text}\n"
            "===\n"
        )

        messages = [LLMMessage(role="user", content=prompt)]
        # 简历文本量较大，给到 8K 输出 token，温度低保证稳定
        result = await self.llm_client.analyze_with_structured_output(
            messages=messages,
            output_schema=schema,
            max_tokens=8000,
            temperature=0.1,
        )

        # 兜底校验 + 补 validation 字段（保持与正则路径返回结构一致）
        result.setdefault("header", {})
        result["header"].setdefault("contact", {"phone": None, "email": None})
        result.setdefault("experience", [])
        result.setdefault("projects", [])
        result.setdefault("skills", {"technical": [], "soft": []})
        result.setdefault("education", [])
        result["validation"] = self._validate_completeness(
            result["header"], result["experience"], result["skills"], result["education"]
        )
        return result

    def _extract_text(self, pdf_path: str) -> str:
        """提取 PDF 文本"""
        try:
            doc = pymupdf.open(pdf_path)
            text = ""
            for page in doc:
                text += page.get_text()
            return text
        except Exception as e:
            logger.error(f"提取文本失败: {e}")
            raise

    def _identify_sections(self, lines: List[str]) -> Dict[str, int]:
        """
        识别章节位置

        Returns:
            {章节名: 行号}
        """
        sections = {}

        for i, line in enumerate(lines):
            line_lower = line.lower()

            for section_name, keywords in self.SECTION_KEYWORDS.items():
                if section_name not in sections:
                    for keyword in keywords:
                        # 精确匹配或包含匹配
                        if keyword.lower() in line_lower:
                            # 章节标题通常较短且不包含过多内容
                            if len(line) < 60:
                                sections[section_name] = i
                                logger.debug(f"识别章节 '{section_name}' 在行 {i}: {line[:50]}")
                                break

        return sections

    def _get_section_lines(self, lines: List[str], sections: Dict[str, int],
                          section_name: str) -> List[str]:
        """获取指定章节的所有行"""
        if section_name not in sections:
            return []

        start_line = sections[section_name]

        # 找到下一个章节的位置
        end_line = len(lines)
        for name, line_num in sections.items():
            if line_num > start_line and line_num < end_line:
                end_line = line_num

        # 跳过章节标题
        return lines[start_line + 1:end_line]

    def _parse_header(self, lines: List[str], text: str) -> Dict[str, Any]:
        """解析头部信息（姓名、联系方式、简介）"""
        header = {
            "name": "Unknown",
            "contact": {"phone": None, "email": None},
            "summary": None
        }

        # 第一行通常是姓名
        if lines:
            first_line = lines[0]
            # 过滤掉单独的电话/邮箱
            if not any(x in first_line for x in ['@', '.com', 'tel:', 'phone:', '电话']):
                header["name"] = first_line.strip()

        # 从前10行中提取联系方式
        for line in lines[:10]:
            # 提取邮箱
            email_match = re.search(r'[\w.-]+@[\w.-]+\.\w+', line)
            if email_match:
                header["contact"]["email"] = email_match.group()

            # 提取电话 (支持多种格式)
            # 英文: +(852) 6222-4603, (86) 13711171888
            # 中文: 13713510929
            phone_patterns = [
                r'\+?\d{1,4}[\s-]?\(?\d{2,4}\)?[\s-]?\d{3,4}[\s-]?\d{3,4}',
                r'\d{11}',  # 中文11位手机号
                r'[(\d\s\-\+]{10,20}'  # 通用格式
            ]
            for pattern in phone_patterns:
                phone_match = re.search(pattern, line)
                if phone_match and not '@' in phone_match.group():
                    phone = re.sub(r'[^\d\+\-]', '', phone_match.group())
                    if len(phone) >= 10:
                        header["contact"]["phone"] = phone_match.group()
                        break

        # 提取个人简介（Personal Summary 或 个人优势 后的第一段）
        for i, line in enumerate(lines):
            if any(kw in line.lower() for kw in ['personal summary', '个人优势', '个人简介']):
                # 获取接下来几行
                summary_lines = []
                for j in range(i + 1, min(i + 5, len(lines))):
                    if lines[j] and not lines[j].startswith('•') and len(lines[j]) > 20:
                        summary_lines.append(lines[j])
                if summary_lines:
                    header["summary"] = ' '.join(summary_lines)
                break

        return header

    def _parse_experience(self, lines: List[str], sections: Dict[str, int]) -> List[Dict[str, Any]]:
        """解析工作经历"""
        experiences = []

        if 'experience' not in sections:
            return experiences

        section_lines = self._get_section_lines(lines, sections, 'experience')

        i = 0
        while i < len(section_lines):
            line = section_lines[i].strip()

            # 跳过空行
            if not line:
                i += 1
                continue

            # 判断是哪种格式
            exp_data = None

            # 格式1: 中文 - 时间行 + 公司 + 职位
            # 2022.07-至今
            # 深圳市星盛商业管理有限公司
            # 管培生
            #  描述内容
            if re.match(r'^\d{4}\.\d{2}-', line) or re.match(r'^\d{4}年\d{1,2}月', line):
                # 查找所有相关的描述行（以  或 • 开头）
                description_lines = []
                j = i + 3  # 跳过时间、公司、职位三行
                while j < len(section_lines):
                    next_line = section_lines[j].strip()
                    # 检查是否是描述行（以 bullet 字符开头）
                    # 常见的 bullet 字符
                    bullet_chars = ['•', '•', '', '', '●', '●', '◆', '◆', '']
                    is_description = False
                    for bc in bullet_chars:
                        if next_line.startswith(bc):
                            is_description = True
                            # 检查 bullet 是否单独占一行（只是 bullet 字符）
                            clean_line = next_line
                            for bc in bullet_chars:
                                clean_line = clean_line.replace(bc, '')
                            clean_line = clean_line.strip()

                            if not clean_line:
                                # bullet 单独占一行，描述内容在下一行（可能跨多行）
                                j += 1  # 跳过 bullet 行
                                # 收集连续的非空行，直到下一个 bullet 或新的工作经历
                                current_desc = []
                                while j < len(section_lines):
                                    desc_line = section_lines[j].strip()
                                    if not desc_line:
                                        j += 1
                                        continue
                                    # 检查是否是新的 bullet（新的描述点）
                                    is_new_bullet = any(desc_line.startswith(bc) for bc in bullet_chars)
                                    # 检查是否是新的工作经历（以数字开头的时间）
                                    is_new_exp = re.match(r'^\d{4}\.\d{2}-', desc_line) or re.match(r'^\d{4}年\d{1,2}月', desc_line)
                                    if is_new_bullet or is_new_exp:
                                        break
                                    current_desc.append(desc_line)
                                    j += 1
                                if current_desc:
                                    description_lines.append(' '.join(current_desc))
                            else:
                                # bullet 和描述在同一行
                                description_lines.append(clean_line)
                                j += 1
                            break

                    if not is_description:
                        if not next_line:
                            j += 1
                        else:
                            # 遇到新的工作经历，停止
                            break

                exp_data = self._parse_experience_cn_format(section_lines, i)
                if exp_data:
                    exp_data["description"] = ' '.join(description_lines) if description_lines else ""
                    i = j  # 跳到下一个工作经历
                    experiences.append(exp_data)
                    continue

            # 格式2: 英文 - Company | Title | Date | Location (可能在同一行或分开)
            if '|' in line and not any(kw in line for kw in ['•', '']):
                exp_data = self._parse_experience_en_format(section_lines, i)
                if exp_data:
                    # 收集所有描述行（以 bullet 字符开头）
                    description_lines = []
                    j = i + 1
                    bullet_chars = ['•', '•', '', '', '●', '●', '◆', '◆']
                    while j < len(section_lines):
                        next_line = section_lines[j].strip()
                        is_description = False
                        for bc in bullet_chars:
                            if next_line.startswith(bc):
                                is_description = True
                                clean_line = next_line
                                for bc in bullet_chars:
                                    clean_line = clean_line.replace(bc, '')
                                description_lines.append(clean_line.strip())
                                j += 1
                                break

                        if not is_description:
                            if not next_line:
                                j += 1
                            else:
                                # 遇到新的工作经历，停止
                                break

                    exp_data["description"] = ' '.join(description_lines) if description_lines else ""
                    i = j
                    experiences.append(exp_data)
                    continue

            i += 1

        return experiences

    def _parse_experience_cn_format(self, lines: List[str], start_idx: int) -> Optional[Dict[str, Any]]:
        """解析中文格式的工作经历"""
        if start_idx + 2 >= len(lines):
            return None

        # 提取时间
        time_line = lines[start_idx].strip()
        time_match = re.search(r'(\d{4})\.(\d{1,2})-(\d{4})\.(\d{1,2})|(\d{4}\.\d{1,2})-至今', time_line)
        if time_match:
            parts = time_match.groups()
            if parts[0]:  # 完整日期格式
                start_date = f"{parts[0]}.{parts[1]}"
                end_date = f"{parts[2]}.{parts[3]}" if parts[2] else '至今'
            else:
                start_date = parts[4]
                end_date = '至今'
        else:
            start_date = 'Unknown'
            end_date = 'Unknown'

        # 提取公司
        company = lines[start_idx + 1].strip()
        # 过滤掉明显不是公司的内容
        if '|' in company or '•' in company or len(company) < 2:
            return None

        # 提取职位
        title = lines[start_idx + 2].strip() if start_idx + 2 < len(lines) else 'Unknown'

        return {
            "company": company,
            "title": title,
            "start_date": start_date,
            "end_date": end_date,
            "location": None,
            "description": ""
        }

    def _parse_experience_en_format(self, lines: List[str], start_idx: int) -> Optional[Dict[str, Any]]:
        """解析英文格式的工作经历

        支持多种格式：
        1. Company | Title | Date | Location (单行或多行)
        2. Company | Title Date | Location (Date 可能和 Title 在同一部分)
        """
        line1 = lines[start_idx].strip()

        # 提取公司
        parts = line1.split('|', 1)  # 只分割第一个 |
        if len(parts) < 2:
            return None

        company = parts[0].strip()
        rest = parts[1].strip()  # 剩余部分可能包含 Title | Date | Location

        # 解析剩余部分
        title = ""
        date_part = ""
        location = None
        start_date = None
        end_date = None

        # 检查剩余部分是否还有 |
        if '|' in rest:
            # 格式: Title | Date | Location
            sub_parts = [p.strip() for p in rest.split('|')]

            # 逐个检查子部分，找到日期和地点
            for i, part in enumerate(sub_parts):
                # 查找日期模式
                date_match = re.search(r'([A-Z][a-z]+\s+\d{4}.*)', part)
                if date_match:
                    # 日期匹配到，split 标题和日期
                    date_part = date_match.group(1)
                    title_idx = date_match.start()
                    title = part[:title_idx].strip()
                    if not title and i == 0:
                        # 如果第一部分就是日期，说明可能没有标题
                        title = ""

                    # 检查日期之后的部分是否有地点
                    if i + 1 < len(sub_parts):
                        loc_candidate = sub_parts[i + 1].strip()
                        if loc_candidate and not re.search(r'\d{4}', loc_candidate):
                            location = loc_candidate
                    break
                else:
                    # 这个部分不包含日期，可能是标题的一部分
                    if not title:
                        title = part

            # 如果没有找到日期，整行都是标题
            if not date_part:
                title = rest

            # 如果当前行没有日期，检查下一行
            if not date_part and start_idx + 1 < len(lines):
                line2 = lines[start_idx + 1].strip()
                if '|' in line2:
                    parts2 = [p.strip() for p in line2.split('|')]
                    if parts2:
                        date_part = parts2[0]
                        if len(parts2) > 1:
                            location = parts2[1] if parts2[1] else None
                else:
                    date_part = line2
        else:
            # 没有 |，尝试直接在 rest 中查找日期
            date_match = re.search(r'([A-Z][a-z]+\s+\d{4}.*)', rest)
            if date_match:
                date_part = date_match.group(1)
                # 日期之前的部分是标题
                title_idx = date_match.start()
                title = rest[:title_idx].strip()
            else:
                # 没有找到日期，可能是纯标题行
                title = rest
                # 检查下一行是否有日期
                if start_idx + 1 < len(lines):
                    line2 = lines[start_idx + 1].strip()
                    if '|' in line2:
                        parts2 = [p.strip() for p in line2.split('|')]
                        if parts2:
                            date_part = parts2[0]
                            if len(parts2) > 1:
                                location = parts2[1] if parts2[1] else None
                    else:
                        date_part = line2

        # 解析日期
        if date_part:
            date_match = re.search(r'([A-Z][a-z]+)\s+(\d{4})\s*–\s*([A-Z][a-z]+)?\s*(\d{4}|Present)', date_part)
            if date_match:
                groups = date_match.groups()
                start_date = f"{groups[0]} {groups[1]}"
                if groups[3] == 'Present':
                    end_date = 'Present'
                elif groups[3]:
                    end_date = f"{groups[2]} {groups[3]}"
                else:
                    end_date = None

        return {
            "company": company,
            "title": title,
            "start_date": start_date,
            "end_date": end_date,
            "location": location,
            "description": ""
        }

    def _parse_projects(self, lines: List[str], sections: Dict[str, int]) -> List[Dict[str, Any]]:
        """解析项目经验"""
        projects = []

        if 'projects' not in sections:
            return projects

        section_lines = self._get_section_lines(lines, sections, 'projects')

        for line in section_lines:
            line = line.strip()
            if not line or not line.startswith('•'):
                continue

            # 格式: •ProjectName: Description
            if ':' in line:
                parts = line.split(':', 1)
                name = parts[0][1:].strip()  # 去掉 •
                description = parts[1].strip() if len(parts) > 1 else ""

                # 提取技术栈
                tech_stack = []
                for skill in self.TECH_SKILL_KEYWORDS:
                    if skill in description:
                        tech_stack.append(skill)

                projects.append({
                    "name": name,
                    "description": description,
                    "role": None,
                    "tech_stack": tech_stack
                })

        return projects

    def _parse_skills(self, lines: List[str], sections: Dict[str, int], text: str) -> Dict[str, List[str]]:
        """解析技能"""
        skills = {
            "technical": [],
            "soft": []
        }

        # 如果有专门的技能章节
        if 'skills' in sections:
            section_lines = self._get_section_lines(lines, sections, 'skills')

            # 收集所有文本
            skill_text = ' '.join(section_lines)

            # 解析分类技能（如: Technical: ..., Marketing: ...）
            categories = re.findall(r'•?([A-Z][a-zA-Z\s]+):\s*(.*?)(?=•|\Z)', skill_text)
            for category, value in categories:
                category_lower = category.lower()
                if 'technical' in category_lower or 'language' not in category_lower:
                    # 技能列表
                    for skill in self.TECH_SKILL_KEYWORDS:
                        if skill in value:
                            if skill not in skills["technical"]:
                                skills["technical"].append(skill)

            # 如果没有分类，直接从文本中提取
            if not categories:
                for line in section_lines:
                    line_stripped = line.strip()
                    if line_stripped.startswith('•'):
                        for skill in self.TECH_SKILL_KEYWORDS:
                            if skill in line_stripped:
                                if skill not in skills["technical"]:
                                    skills["technical"].append(skill)

        # 从全文中提取技能（补充遗漏的）
        for skill in self.TECH_SKILL_KEYWORDS:
            if skill.lower() in text.lower():
                if skill not in skills["technical"] and len(skill) > 2:
                    skills["technical"].append(skill)

        # 提取软技能
        for soft_skill in self.SOFT_SKILL_KEYWORDS:
            if soft_skill.lower() in text.lower():
                if soft_skill not in skills["soft"]:
                    skills["soft"].append(soft_skill)

        return skills

    def _parse_education(self, lines: List[str], sections: Dict[str, int]) -> List[Dict[str, Any]]:
        """解析教育背景"""
        education = []

        if 'education' not in sections:
            return education

        section_lines = self._get_section_lines(lines, sections, 'education')

        i = 0
        while i < len(section_lines):
            line = section_lines[i].strip()

            if not line or line.startswith('•'):
                i += 1
                continue

            # 判断是哪种格式

            # 格式1: 中文 - 时间 + 学校 + 专业/学位 (多行)
            # 2021.09-2022.11
            # 英国纽卡斯尔大学
            # 跨文化交际和国际市场营销/硕士
            if re.match(r'^\d{4}\.\d{2}-', line) or re.match(r'^\d{4}年\d{1,2}月', line):
                edu = self._parse_education_cn_format(section_lines, i)
                if edu:
                    education.append(edu)
                    i += 3
                    continue

            # 格式2: 英文 - 学校 + 时间 + 地点 (单行，可能很长)
            # 下一行是学位
            if re.search(r'[A-Z]', line) and re.search(r'\d{4}', line):
                edu = self._parse_education_en_format(section_lines, i)
                if edu:
                    education.append(edu)
                    i += 2
                    continue

            i += 1

        return education

    def _parse_education_cn_format(self, lines: List[str], start_idx: int) -> Optional[Dict[str, Any]]:
        """解析中文格式的教育背景"""
        if start_idx + 2 >= len(lines):
            return None

        time_line = lines[start_idx].strip()
        school = lines[start_idx + 1].strip()
        major_degree = lines[start_idx + 2].strip()

        # 解析专业和学位
        if '/' in major_degree:
            parts = major_degree.split('/')
            major = parts[0].strip()
            degree = parts[1].strip() if len(parts) > 1 else ''
        else:
            major = major_degree
            degree = ''

        # 解析时间
        time_match = re.search(r'(\d{4})\.(\d{1,2})-(\d{4})\.(\d{1,2})', time_line)
        if time_match:
            start_date = f"{time_match.group(1)}.{time_match.group(2)}"
            end_date = f"{time_match.group(3)}.{time_match.group(4)}"
        else:
            start_date = None
            end_date = None

        return {
            "school": school,
            "degree": degree,
            "major": major,
            "start_date": start_date,
            "end_date": end_date,
            "gpa": None
        }

    def _parse_education_en_format(self, lines: List[str], start_idx: int) -> Optional[Dict[str, Any]]:
        """解析英文格式的教育背景"""
        line = lines[start_idx].strip()

        # 解析学校名称（去除日期和地点信息）
        # 格式: "The University of Edinburgh (QS 16)                                                                         Sep 2017 – Jun 2020 | Edinburgh, UK   "
        school_match = re.match(r'^([A-Z][^\d\|]+)', line)
        if school_match:
            school = school_match.group(1).strip()
        else:
            # 尝试提取大写开头的学校名
            school_match = re.search(r'([A-Z][A-Za-z\s]+)\s+\(', line)
            if school_match:
                school = school_match.group(1).strip()
            else:
                school = line.split('(')[0].strip()

        # 解析时间
        time_match = re.search(r'([A-Z][a-z]+)\s+(\d{4})\s*–\s*([A-Z][a-z]+)\s+(\d{4})', line)
        if time_match:
            start_date = f"{time_match.group(1)} {time_match.group(2)}"
            end_date = f"{time_match.group(3)} {time_match.group(4)}"
        elif 'Present' in line:
            start_match = re.search(r'([A-Z][a-z]+\s+\d{4})\s*–', line)
            start_date = start_match.group(1) if start_match else None
            end_date = 'Present'
        else:
            start_date = None
            end_date = None

        # 解析地点
        location_match = re.search(r'\|\s*([A-Za-z,\s]+)$', line)
        location = location_match.group(1).strip() if location_match else None

        # 下一行通常是学位
        if start_idx + 1 < len(lines):
            degree_line = lines[start_idx + 1].strip()
            if degree_line.startswith('•'):
                degree = degree_line[1:].strip()
            else:
                degree = degree_line
        else:
            degree = None

        return {
            "school": school,
            "degree": degree,
            "major": None,
            "start_date": start_date,
            "end_date": end_date,
            "location": location,
            "gpa": None
        }

    def _validate_completeness(self, header: Dict[str, Any],
                               experience: List[Dict[str, Any]],
                               skills: Dict[str, List[str]],
                               education: List[Dict[str, Any]]) -> Dict[str, Any]:
        """验证解析结果的完整性"""
        issues = []
        missing_fields = []

        # 检查姓名
        if not header.get('name') or header['name'] == 'Unknown':
            missing_fields.append('姓名')
            issues.append('未找到姓名信息')

        # 检查联系方式
        if not header.get('contact', {}).get('email'):
            missing_fields.append('邮箱')
            issues.append('未找到邮箱地址')
        if not header.get('contact', {}).get('phone'):
            issues.append('未找到电话号码')

        # 检查工作经历
        if not experience:
            missing_fields.append('工作经历')
            issues.append('未找到工作经历')

        # 检查技能
        if not skills.get('technical') and not skills.get('soft'):
            missing_fields.append('技能')
            issues.append('未找到技能信息')

        # 检查教育背景
        if not education:
            missing_fields.append('教育背景')
            issues.append('未找到教育背景')

        # 计算完整度
        total_fields = 5
        missing_count = len(missing_fields)
        completeness_score = max(0, (total_fields - missing_count) / total_fields)

        return {
            "is_complete": completeness_score >= 0.8,
            "completeness_score": completeness_score,
            "missing_fields": missing_fields,
            "issues": issues
        }

    def export_to_json(self, parsed_data: Dict[str, Any], output_path: str):
        """导出解析结果为 JSON"""
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(parsed_data, f, ensure_ascii=False, indent=2)
        logger.info(f"解析结果已导出到: {output_path}")