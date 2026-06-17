# tools/scraper/jd_analyzer_enhanced.py
"""
JD 分析器增强版 - 支持中英文 JD 深度分析
"""
from typing import Dict, Any, Optional, List
import re
import json
import requests
from bs4 import BeautifulSoup
from loguru import logger
from tools.llm import LLMClient, LLMMessage
from tools.scraper.boss_scraper import BossScraper
from tools.scraper.jobsdb_scraper import JobsDBScraper


class JDAnalyzerEnhanced:
    """JD 分析器增强版 - 支持中英文"""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        """
        初始化 JD 分析器

        Args:
            llm_client: LLM 客户端（可选，不传则使用规则分析）
        """
        self.llm_client = llm_client
        self.logger = logger.bind(component="jd_analyzer_enhanced")

        # 初始化爬虫（用于获取 JD）
        self._scrapers = {
            "boss": BossScraper()
        }
        self._playwright_scrapers = {
            "jobsdb": JobsDBScraper
        }
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })

        # 技术关键词（中英文）
        self.tech_keywords = {
            "backend": ["Python", "Java", "Go", "Node.js", "JavaScript", "Backend", "API", "REST", "Microservices", "后端", "微服务"],
            "frontend": ["React", "Vue", "Angular", "TypeScript", "JavaScript", "Frontend", "Front-end", "前端"],
            "fullstack": ["Full Stack", "Full-stack", "Fullstack", "全栈", "前后端"],
            "data": ["Python", "SQL", "MySQL", "PostgreSQL", "MongoDB", "Data Analysis", "Data Mining", "Data Visualization", "机器学习", "数据分析"],
            "devops": ["Docker", "Kubernetes", "CI/CD", "DevOps", "AWS", "GCP", "Azure", "运维"],
            "mobile": ["iOS", "Android", "Flutter", "React Native", "Mobile", "移动端"],
            "ai": ["Machine Learning", "Deep Learning", "NLP", "AI", "LLM", "GPT", "Prompt Engineering", "机器学习", "深度学习", "大模型"],
            "marketing": ["Digital Marketing", "Social Media", "SEO", "SEM", "Content Marketing", "数字营销"],
            "analytics": ["Google Analytics", "Data Analytics", "Business Intelligence", "Power BI", "Tableau"],
            "design": ["UI/UX", "Figma", "Sketch", "Adobe XD", "设计"],
        }

        # 英文隐性要求关键词
        self.implicit_patterns_en = {
            "leadership": ["lead", "leader", "manager", "manage", "supervise", "guide", "mentor", "head", "director"],
            "teamwork": ["team", "collaborate", "collaboration", "cross-functional", "partner", "work with", "together"],
            "problem_solving": ["solve", "problem", "challenge", "solution", "optimize", "improve", "troubleshoot", "debug"],
            "learning": ["learn", "curious", "eager", "new technology", "adapt", "fast-paced", "continuous improvement", "self-starter"],
            "pressure": ["deadline", "tight", "urgent", "pressure", "stress", "overtime", "crunch"],
            "communication": ["communicate", "communication", "present", "report", "stakeholder", "client", "speak"],
            "english": ["english", "fluent", "written", "verbal", "cantonese", "mandarin"],
        }

        # 中文隐性要求关键词
        self.implicit_patterns_zh = {
            "leadership": ["带领", "管理", "负责", "主导", "Leader", "Lead", "组长", "经理"],
            "teamwork": ["协作", "团队合作", "沟通", "Cross-functional"],
            "problem_solving": ["解决", "挑战", "优化", "性能", "问题"],
            "learning": ["学习", "快速", "新技术", "适应"],
            "pressure": ["压力", "deadline", "紧张", "加班"],
            "communication": ["沟通", "表达", "汇报"],
            "english": ["英文", "English", "英语"],
        }

    async def parse_from_url(self, url: str) -> Dict[str, Any]:
        """
        从 URL 获取并分析 JD

        Args:
            url: JD URL

        Returns:
            分析结果
        """
        # 1. 识别平台
        platform = self._identify_platform(url)

        # 2. 获取 JD 文本
        jd_text = await self._fetch_jd_text(url, platform)

        # 3. 分析 JD
        return await self.parse_from_text(jd_text)

    async def parse_from_text(self, text: str) -> Dict[str, Any]:
        """
        从文本分析 JD（支持中英文）

        Args:
            text: JD 文本

        Returns:
            分析结果
        """
        self.logger.info("开始分析 JD（增强版）")

        # 检测语言
        is_english = self._is_english(text)
        self.logger.info(f"检测到语言：{'英文' if is_english else '中文'}")

        # 提取基本信息
        title = self._extract_title(text, is_english)
        company = self._extract_company(text, is_english)
        location = self._extract_location(text, is_english)
        salary_range = self._extract_salary(text, is_english)

        # 提取要求
        core_requirements = self._extract_core_requirements(text, is_english)
        preferred_requirements = self._extract_preferred_requirements(text, is_english)

        # 使用 LLM 进行深度分析（如果有）
        if self.llm_client:
            try:
                deep_analysis = await self._analyze_with_llm(text, is_english)

                # 合并结果，LLM 结果优先
                implicit_requirements = deep_analysis.get("implicit_requirements", "")
                keywords = deep_analysis.get("keywords", [])

                # 如果 LLM 提取的核心要求更详细，使用 LLM 的结果
                if len(deep_analysis.get("core_requirements", [])) > len(core_requirements):
                    core_requirements = deep_analysis["core_requirements"]

            except Exception as e:
                self.logger.warning(f"LLM 分析失败，使用规则分析: {e}")
                implicit_requirements = self._extract_implicit_requirements(text, is_english)
                keywords = self._extract_keywords(text, is_english)
        else:
            implicit_requirements = self._extract_implicit_requirements(text, is_english)
            keywords = self._extract_keywords(text, is_english)

        return {
            "title": title,
            "company": company,
            "location": location,
            "salary_range": salary_range,
            "core_requirements": core_requirements,
            "preferred_requirements": preferred_requirements,
            "implicit_requirements": implicit_requirements,
            "keywords": keywords,
            "language": "en" if is_english else "zh",
            "raw_text": text
        }

    def _is_english(self, text: str) -> bool:
        """检测文本是否为英文"""
        # 简单检测：如果英文单词占比超过70%，则认为是英文
        english_chars = sum(1 for c in text if c.isalpha() and c.isascii())
        total_chars = sum(1 for c in text if c.isalpha())

        if total_chars == 0:
            return False

        return (english_chars / total_chars) > 0.7

    def _extract_title(self, text: str, is_english: bool) -> str:
        """提取职位名称（支持中英文）"""
        if is_english:
            # 英文 JD 职位提取策略

            # 尝试从前几行提取（最可靠的方法）
            lines = text.split('\n')
            for i, line in enumerate(lines[:8]):
                line = line.strip()

                # 跳过空行、太长的行、明显的非职位行
                if not line or len(line) > 80:
                    continue

                # 跳过公司介绍、日期等
                skip_keywords = ["about", "posted", "position", "company", "location", "salary", "description", "requirements", "we are", "limited"]
                if any(kw in line.lower() for kw in skip_keywords):
                    continue

                # 检查是否像职位名称
                if self._looks_like_job_title(line):
                    # 清理：移除 | 后面的内容（如 "| AI & Human Intelligence | Social Power"）
                    pipe_idx = line.find(' | ')
                    if pipe_idx > 0:
                        # 检查 | 后面是否是公司名或地点
                        after_pipe = line[pipe_idx + 3:]
                        if any(kw in after_pipe.lower() for kw in ["company", "hong kong", "ai", "intelligence"]):
                            return line[:pipe_idx].strip()
                    return line

            # 使用模式匹配作为后备
            patterns = [
                r'^(Social Media Analyst|Senior Analyst|Manager|Director|Engineer|Developer|Designer|Specialist|Consultant|Lead)(?:\s*/\s*(?:Senior|Junior|Lead|Principal|Staff|Director|Manager|Analyst|Engineer|Developer|Designer|Specialist|Consultant))?',
                r'^(?:Senior|Junior|Lead|Principal|Staff|Director)\s+(?:Analyst|Engineer|Developer|Designer|Specialist|Consultant|Manager|Director)',
            ]

            for pattern in patterns:
                match = re.search(pattern, text, re.MULTILINE | re.IGNORECASE)
                if match:
                    title = match.group(1).strip()
                    if len(title) < 50:
                        return title
        else:
            # 中文 JD 职位提取
            patterns = [
                r'职位名称[：:]\s*(.+?)(?:\n|$)',
                r'岗位[：:]\s*(.+?)(?:\n|$)',
                r'Position[：:]\s*(.+?)(?:\n|$)',
                r'Title[：:]\s*(.+?)(?:\n|$)'
            ]

            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    return match.group(1).strip()

            # 尝试从第一行提取
            lines = text.split('\n')
            for line in lines[:5]:
                if line.strip() and len(line.strip()) < 50:
                    return line.strip()

        return "Unknown Position"

    def _looks_like_job_title(self, text: str) -> bool:
        """判断文本是否像职位名称"""
        text = text.strip()

        # 必须包含职位关键词
        job_keywords = [
            "analyst", "manager", "director", "engineer", "developer", "designer",
            "specialist", "consultant", "coordinator", "assistant", "lead",
            "senior", "junior", "head", "chief", "principal", "staff",
            "architect", "scientist", "officer", "representative", "associate"
        ]

        has_job_keyword = any(kw in text.lower() for kw in job_keywords)

        # 不能是纯数字或特殊字符
        is_meaningful = any(c.isalpha() for c in text)

        # 长度合理
        is_proper_length = 5 < len(text) < 80

        # 不太可能包含这些词
        not_excluded = all(
            kw not in text.lower()
            for kw in ["posted", "about", "description", "requirements", "we are", "looking for"]
        )

        return has_job_keyword and is_meaningful and is_proper_length and not_excluded

    def _extract_company(self, text: str, is_english: bool) -> str:
        """提取公司名称（支持中英文）"""
        if is_english:
            # 英文 JD 公司提取

            # 尝试模式匹配
            patterns = [
                # 公司后缀模式
                r'([A-Z][a-zA-Z\s&\-\.,]+\s+(?:Limited|Ltd|Inc|Corp|LLC|Co\.))',
                # About Company
                r'About\s+([A-Z][a-zA-Z\s&\-\.,]+(?:Limited|Ltd|Inc|Corp)?)',
            ]

            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    company = match.group(1).strip()
                    # 移除多余的空格和标点
                    company = re.sub(r'\s+', ' ', company)
                    company = company.strip()
                    # 移除连续重复
                    words = company.split()
                    seen = set()
                    unique_words = []
                    for word in words:
                        word_clean = word.strip(' ,.')
                        if word_clean and word_clean not in seen:
                            seen.add(word_clean)
                            unique_words.append(word_clean)
                    company = ' '.join(unique_words)
                    if 5 < len(company) < 80:
                        return company

            # 从文本中查找公司模式
            lines = text.split('\n')
            for i, line in enumerate(lines[:20]):
                line = line.strip()

                # 跳过明显的非公司行
                skip_keywords = ["about", "posted", "position", "location", "salary", "description", "requirements", "we are", "looking for", "social media"]
                if any(kw in line.lower() for kw in skip_keywords):
                    continue

                if self._looks_like_company_name(line):
                    # 确保这不是职位名称
                    if not any(kw in line.lower() for kw in ["analyst", "manager", "engineer", "developer", "designer", "director"]):
                        return line
        else:
            # 中文 JD 公司提取
            patterns = [
                r'公司名称[：:]\s*(.+?)(?:\n|$)',
                r'公司[：:]\s*(.+?)(?:\n|$)',
                r'Company[：:]\s*(.+?)(?:\n|$)'
            ]

            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    return match.group(1).strip()

        return "Unknown Company"

    def _looks_like_company_name(self, text: str) -> bool:
        """判断文本是否像公司名称"""
        text = text.strip()

        # 公司常见后缀
        company_suffixes = [
            "Limited", "Ltd", "Inc", "Corporation", "Corp", "LLC",
            "Company", "Co", "Group", "Holdings", "Technologies",
            "Solutions", "Systems", "International", "Global"
        ]

        has_suffix = any(text.lower().endswith(suffix.lower()) for suffix in company_suffixes)

        # 首字母大写
        is_capitalized = text[0].isupper() if text else False

        # 长度合理
        is_proper_length = 3 < len(text) < 80

        # 不太可能包含这些词
        not_excluded = all(
            kw not in text.lower()
            for kw in ["posted", "about", "description", "requirements", "we are", "looking for", "job title"]
        )

        return (has_suffix or is_capitalized) and is_proper_length and not_excluded

    def _extract_location(self, text: str, is_english: bool) -> str:
        """提取工作地点（支持中英文）"""
        if is_english:
            # 英文地点提取 - 优先匹配城市名

            # 常见城市列表（按长度降序，优先匹配长的）
            cities = [
                "Hong Kong", "Singapore", "New York", "San Francisco", "Los Angeles",
                "San Jose", "New York City", "Shanghai", "Beijing", "Shenzhen",
                "Guangzhou", "Shenzhen", "Tokyo", "Taipei", "Seoul", "Bangalore",
                "Mumbai", "Dubai", "Berlin", "Paris", "London", "Vancouver",
                "Toronto", "Sydney", "Melbourne", "Chicago", "Boston", "Seattle",
                "Austin", "Dallas", "Atlanta", "Denver", "Phoenix", "Portland"
            ]

            for city in cities:
                # 使用单词边界匹配
                pattern = r'\b' + re.escape(city) + r'\b'
                if re.search(pattern, text, re.IGNORECASE):
                    return city

            # 使用模式匹配作为后备
            patterns = [
                r'Location[:\s]*\n?\s*([A-Z][a-zA-Z\s,\-]+)',
                r'Work Location[:\s]*\n?\s*([A-Z][a-zA-Z\s,\-]+)',
                r'in\s+([A-Z][a-zA-Z\s]+)(?:\s+and|\s+\||\s+at|$)',
            ]

            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    location = match.group(1).strip()
                    # 确保是合理的地点（不是其他文本）
                    if len(location) < 50 and any(c.isupper() for c in location):
                        return location
        else:
            # 中文地点提取
            patterns = [
                r'工作地点[：:]\s*(.+?)(?:\n|$)',
                r'地点[：:]\s*(.+?)(?:\n|$)',
                r'Location[：:]\s*(.+?)(?:\n|$)'
            ]

            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    return match.group(1).strip()

        return "Unknown"

    def _extract_salary(self, text: str, is_english: bool) -> str:
        """提取薪资范围（支持中英文）"""
        if is_english:
            # 英文薪资提取
            patterns = [
                # HK$ format
                r'(?:HK\$|HKD|\$)\s*(\d+[kK]?[,\-]?\s*\d*[kK]?)',
                # Salary: X-Y
                r'Salary[:\s]*\n?\s*([A-Z$]?\d+[kK]?[,\-]?\s*\d*[kK]?[A-Z$]?)',
                # Competitive salary / Negotiable
                r'(Competitive\s+salary|Negotiable|Salary\s+(?:is|will\s+be)\s+(?:negotiable|competitive))',
                # Numeric range
                r'(\d+[,\-]+\d+)\s*(?:per month|monthly|p\.m\.)',
            ]

            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    salary = match.group(1).strip()
                    if len(salary) < 30:
                        return salary
        else:
            # 中文薪资提取
            patterns = [
                r'薪资[：:]\s*(.+?)(?:\n|$)',
                r'待遇[：:]\s*(.+?)(?:\n|$)',
                r'薪酬[：:]\s*(.+?)(?:\n|$)',
                r'Salary[：:]\s*(.+?)(?:\n|$)'
            ]

            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    return match.group(1).strip()

        return "Negotiable" if is_english else "面议"

    def _extract_core_requirements(self, text: str, is_english: bool) -> List[str]:
        """提取核心要求（支持中英文）"""
        requirements = []

        if is_english:
            # 英文 JD 核心要求提取

            # 方法1：找到 "Who We Are Looking For" 章节
            who_section_match = re.search(
                r'(?i)(?:Who We Are Looking For|What We Need|What You Need|Your Profile|Requirements)[:\s]*\n+(.*?)(?=\n\n(?:Experience|Why|What|How|Note|Interested)|$)',
                text, re.DOTALL
            )

            section_text = ""
            if who_section_match:
                section_text = who_section_match.group(1)

            # 方法2：如果没有找到，从 "What You Will Be Doing" 提取
            if not section_text:
                what_section_match = re.search(
                    r'(?i)(?:What You Will Be Doing|Your Role|Responsibilities)[:\s]*\n+(.*?)(?=\n\n|\n(?:Who|We|You|Requirements|Qualifications)|$)',
                    text, re.DOTALL
                )
                if what_section_match:
                    section_text = what_section_match.group(1)

            # 方法3：如果没有找到章节，从整个文本提取
            if not section_text:
                section_text = text[:2000]

            # 提取要求项（支持多种格式）
            requirement_items = []

            # 方法：大写开头 + 冒号（过滤掉章节标题）
            items = re.findall(r'^([A-Z][a-zA-Z\s\-]+):\s*([^\n]+)$', section_text, re.MULTILINE)
            for key, value in items:
                key = key.strip()
                value = value.strip()
                # 过滤掉章节标题和不相关的行
                if len(key) > 5 and len(value) > 10:
                    if not any(kw in key.lower() for kw in ["experience", "levels", "why", "interested", "how to apply", "we value"]):
                        # 清理值
                        value = re.sub(r'\s+', ' ', value)
                        requirement_items.append(f"{key}: {value}")

            # 去重并限制数量
            seen = set()
            for req in requirement_items:
                # 使用首词（第一个单词）作为去重键
                first_word = req.split()[0].lower() if req.split() else ""
                if first_word and first_word not in seen:
                    seen.add(first_word)
                    requirements.append(req)
                elif not first_word:
                    # 如果没有单词，使用整个字符串
                    req_lower = req.lower()
                    if req_lower not in seen:
                        seen.add(req_lower)
                        requirements.append(req)

        else:
            # 中文 JD 核心要求提取
            patterns = [
                r'Requirements[:\s]*\n(.*?)(?=\n\n|\n\d+\.|\nPreferred|\nQualifications)',
                r'Qualifications[:\s]*\n(.*?)(?=\n\n|\n\d+\.|\nPreferred)'
            ]

            section_text = ""
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
                if match:
                    section_text = match.group(1)

            # 中文章节查找
            if not section_text:
                for keyword in ['【任职要求】', '【职位要求】', '【岗位要求】', '【要求】', '任职要求', '职位要求', '岗位要求']:
                    idx = text.find(keyword)
                    if idx >= 0:
                        end_patterns = ['【加分项】', '【优先】', '【职责】', '【职位描述】', '加分项', '职责', '职位描述']
                        end_idx = len(text)
                        for end_pattern in end_patterns:
                            temp_idx = text.find(end_pattern, idx + len(keyword))
                            if temp_idx >= 0 and temp_idx < end_idx:
                                end_idx = temp_idx
                        section_text = text[idx + len(keyword):end_idx].strip()
                        break

            if not section_text:
                section_text = text[:2000]

            # 提取技能关键词
            for tech_list in self.tech_keywords.values():
                for tech in tech_list:
                    if tech.lower() in section_text.lower() and tech not in requirements:
                        requirements.append(tech)

            # 提取带序号的要求
            numbered_items = re.findall(r'[-]\s*(.+?)(?=\n|$)', section_text)
            for item in numbered_items:
                item = item.strip()
                if len(item) > 5 and item not in requirements:
                    requirements.append(item)

        return requirements[:12]

    def _extract_preferred_requirements(self, text: str, is_english: bool) -> List[str]:
        """提取加分项（支持中英文）"""
        requirements = []

        if is_english:
            # 英文加分项提取
            patterns = [
                r'(?:Nice to have|Preferred|Bonus|Plus|Advantageous|Ideal)[:\s]*(?:Qualifications|Requirements)?[:\s]*\n+(.*?)(?=\n\n|\n(?:Why|How|Experience)|$)',
                r'(?i)(?:Experience Levels|Level|Grade)[:\s]*\n+(.*?)(?=\n\n|\n(?:Why|How)|$)',
            ]

            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
                if match:
                    section_text = match.group(1)

                    # 提取带冒号的项目
                    items = re.findall(r'(?:Analyst|Senior|Junior)[^\n]*:\s*([^\n]+)', section_text, re.IGNORECASE)
                    for item in items:
                        item = item.strip()
                        if len(item) > 10 and item not in requirements:
                            requirements.append(item)

                    # 提取bullet points
                    items = re.findall(r'^[•\-\*]\s*([^\n]+)', section_text, re.MULTILINE)
                    for item in items:
                        item = item.strip()
                        if len(item) > 5 and item not in requirements:
                            requirements.append(item)

                    if requirements:
                        break
        else:
            # 中文加分项提取
            patterns = [
                r'[【[]加分项[】]].*?\n(.*?)(?=\n\n|\n[【[]|\n[一二三四五六七八九十])',
                r'[【[]优先[】]].*?\n(.*?)(?=\n\n|\n[【[]|\n[一二三四五六七八九十])',
            ]

            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
                if match:
                    section_text = match.group(1)
                    numbered_items = re.findall(r'[一二三四五六七八九十\d][\.、]\s*(.+?)(?=\n|$)', section_text)
                    numbered_items += re.findall(r'[-]\s*(.+?)(?=\n|$)', section_text)
                    for item in numbered_items:
                        item = item.strip()
                        if len(item) > 3 and item not in requirements:
                            requirements.append(item)
                    if requirements:
                        break

        return requirements[:5]

    def _extract_implicit_requirements(self, text: str, is_english: bool) -> str:
        """提取隐性要求（支持中英文）"""
        implicit = []

        patterns = self.implicit_patterns_en if is_english else self.implicit_patterns_zh
        text_lower = text.lower()

        for trait, pattern_list in patterns.items():
            found = []
            for pattern in pattern_list:
                if pattern.lower() in text_lower:
                    found.append(pattern)

            if found:
                implicit.append(f"{trait}: {', '.join(found)}")

        return "\n".join(implicit) if implicit else ("No significant implicit requirements" if is_english else "无明显隐性要求")

    def _extract_keywords(self, text: str, is_english: bool) -> List[str]:
        """提取岗位关键词（支持中英文）"""
        keywords = set()
        text_lower = text.lower()

        # 提取技术关键词
        for tech_list in self.tech_keywords.values():
            for tech in tech_list:
                if tech.lower() in text_lower and len(tech) > 2:
                    keywords.add(tech)

        # 英文常见关键词
        if is_english:
            common_keywords_en = [
                "Data", "Analysis", "Analytics", "Strategy", "Communication", "Leadership",
                "Teamwork", "Problem Solving", "Project Management", "Customer Service",
                "Sales", "Marketing", "Development", "Design", "Operations",
                "Research", "Optimization", "Performance", "Quality", "Testing",
                "Reporting", "Presentation", "Stakeholder Management", "Client Relations"
            ]
            for keyword in common_keywords_en:
                if keyword.lower() in text_lower:
                    keywords.add(keyword)
        else:
            # 中文常见关键词
            common_keywords_zh = [
                "架构", "设计", "开发", "测试", "运维", "产品", "项目管理",
                "沟通", "协作", "团队", "优化", "性能", "安全", "算法",
                "数据", "机器学习", "人工智能", "云", "大数据", "微服务"
            ]
            for keyword in common_keywords_zh:
                if keyword in text:
                    keywords.add(keyword)

        return sorted(list(keywords))[:15]

    async def _analyze_with_llm(self, jd_text: str, is_english: bool) -> Dict[str, Any]:
        """
        使用 LLM 深度分析 JD

        Args:
            jd_text: JD 文本
            is_english: 是否为英文

        Returns:
            分析结果
        """
        if is_english:
            prompt = f"""Analyze the following job description and extract:

1. Core requirements (must-have skills and experience)
2. Preferred requirements (nice-to-have skills)
3. Implicit requirements (traits not explicitly stated but important)
4. Key job keywords for resume matching

JD:
{jd_text[:4000]}

Please return in JSON format:
```json
{{
    "core_requirements": ["requirement1", "requirement2"],
    "preferred_requirements": ["nice-to-have1", "nice-to-have2"],
    "implicit_requirements": "description of implicit traits",
    "keywords": ["keyword1", "keyword2"]
}}
```

Return only JSON, no other text."""
        else:
            prompt = f"""分析以下职位描述，提取：

1. 核心要求（必须具备的技能/经验）
2. 加分项（优先考虑的能力）
3. 隐性要求（未明说但重要的特质）
4. 岗位关键词（用于简历匹配）

JD：
{jd_text[:4000]}

请以 JSON 格式返回：
```json
{{
    "core_requirements": ["要求1", "要求2"],
    "preferred_requirements": ["加分项1", "加分项2"],
    "implicit_requirements": "隐性要求描述",
    "keywords": ["关键词1", "关键词2"]
}}
```

只返回 JSON，不要有其他文字。"""

        messages = [LLMMessage(role="user", content=prompt)]

        schema = {
            "type": "object",
            "properties": {
                "core_requirements": {"type": "array", "items": {"type": "string"}},
                "preferred_requirements": {"type": "array", "items": {"type": "string"}},
                "implicit_requirements": {"type": "string"},
                "keywords": {"type": "array", "items": {"type": "string"}}
            }
        }

        result = await self.llm_client.analyze_with_structured_output(
            messages=messages,
            output_schema=schema
        )

        return result

    def _identify_platform(self, url: str) -> str:
        """识别招聘平台"""
        if "zhipin.com" in url:
            return "boss"
        elif "liepin.com" in url:
            return "liepin"
        elif "jobsdb.com" in url:
            return "jobsdb"
        elif "zhaopin.com" in url:
            return "zhaopin"
        elif "51job.com" in url:
            return "51job"
        elif "lagou.com" in url:
            return "lagou"
        else:
            return "unknown"

    async def _fetch_jd_text(self, url: str, platform: str) -> str:
        """
        从平台获取 JD 文本

        Args:
            url: JD URL
            platform: 平台名称

        Returns:
            JD 文本
        """
        self.logger.info(f"从 {platform} 获取 JD: {url}")

        try:
            # Boss 直聘 - 使用专用爬虫
            if platform == "boss":
                return await self._fetch_boss_jd(url)

            # JobsDB - 使用 Playwright 爬虫
            elif platform == "jobsdb":
                return await self._fetch_jobsdb_jd(url)

            # 未知平台 - 通用爬取
            else:
                return await self._fetch_generic_jd(url)

        except Exception as e:
            self.logger.error(f"获取 JD 失败: {e}")
            return ""

    async def _fetch_boss_jd(self, url: str) -> str:
        """从 Boss 直聘获取 JD"""
        try:
            scraper = self._scrapers.get("boss")
            if not scraper:
                scraper = BossScraper()
                self._scrapers["boss"] = scraper

            job_detail = await scraper.parse_job(url)

            if not job_detail:
                return await self._fetch_generic_jd(url)

            jd_text = self._format_jd_text(
                title=job_detail.get("title", ""),
                company=job_detail.get("company", ""),
                location=job_detail.get("location", ""),
                salary=job_detail.get("salary_text", ""),
                experience=job_detail.get("experience", ""),
                education=job_detail.get("education", ""),
                description=job_detail.get("description", ""),
                skills=job_detail.get("skills_required", [])
            )

            return jd_text

        except Exception as e:
            self.logger.warning(f"Boss 爬虫失败，尝试通用方法: {e}")
            return await self._fetch_generic_jd(url)

    async def _fetch_jobsdb_jd(self, url: str) -> str:
        """从 JobsDB 获取 JD"""
        self.logger.info("使用 Playwright 获取 JobsDB JD")

        try:
            scraper_class = self._playwright_scrapers.get("jobsdb")
            if not scraper_class:
                self.logger.error("JobsDB scraper class not found")
                return ""

            scraper = scraper_class(headless=True)

            async with scraper:
                if not await scraper.is_logged_in():
                    self.logger.warning("需要登录，但无头模式下无法处理")
                    pass

                jd_text = await scraper.get_jd_text(url)

                if jd_text:
                    self.logger.info(f"成功获取 JobsDB JD: {len(jd_text)} 字符")
                    return jd_text
                else:
                    self.logger.warning("未能获取 JD 文本")
                    return ""

        except Exception as e:
            self.logger.error(f"Playwright 获取 JD 失败: {e}")
            return ""

    async def _fetch_generic_jd(self, url: str) -> str:
        """通用 JD 获取方法"""
        self.logger.info(f"使用通用方法获取 JD: {url}")

        try:
            response = self._session.get(url, timeout=15)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")

            # 尝试多种常见的选择器模式
            title = self._extract_text_by_selectors(soup, [
                "h1.job-title",
                "h1.position-name",
                ".job-name h1",
                "h1",
                ".title",
                "[class*='title']"
            ])

            company = self._extract_text_by_selectors(soup, [
                ".company-name",
                ".company",
                "[class*='company']"
            ])

            location = self._extract_text_by_selectors(soup, [
                ".job-location",
                ".location",
                "[class*='location']",
                "[class*='area']"
            ])

            salary = self._extract_text_by_selectors(soup, [
                ".job-salary",
                ".salary",
                "[class*='salary']"
            ])

            # 获取职位描述
            description = self._extract_description(soup)

            # 格式化输出
            jd_text = self._format_jd_text(
                title=title,
                company=company,
                location=location,
                salary=salary,
                description=description
            )

            return jd_text

        except Exception as e:
            self.logger.error(f"通用方法获取 JD 失败: {e}")
            return ""

    def _extract_text_by_selectors(self, soup: BeautifulSoup, selectors: List[str]) -> str:
        """按选择器列表依次尝试提取文本"""
        for selector in selectors:
            elem = soup.select_one(selector)
            if elem:
                text = elem.get_text(strip=True)
                if text and len(text) < 200:
                    return text
        return ""

    def _extract_description(self, soup: BeautifulSoup) -> str:
        """提取职位描述"""
        selectors = [
            ".job-description",
            ".job-detail",
            ".job-desc",
            ".description",
            "[class*='description']",
            "[class*='detail']",
            "div[class*='job'] p"
        ]

        for selector in selectors:
            elem = soup.select_one(selector)
            if elem:
                text = elem.get_text(separator="\n", strip=True)
                if len(text) > 50:
                    return text

        # 移除不需要的标签
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        # 获取页面文本
        text = soup.get_text(separator="\n", strip=True)

        # 简单清洗
        keywords = ["职责", "要求", "要求", "描述", "任职", "岗位", "技能", "experience", "requirement", "responsibility"]
        paragraphs = text.split("\n")
        filtered = [p for p in paragraphs if any(kw in p.lower() for kw in keywords) or len(p) > 20]

        return "\n".join(filtered[:20])

    def _format_jd_text(
        self,
        title: str = "",
        company: str = "",
        location: str = "",
        salary: str = "",
        experience: str = "",
        education: str = "",
        description: str = "",
        skills: List[str] = None
    ) -> str:
        """将提取的信息格式化为标准 JD 文本"""
        if skills is None:
            skills = []

        lines = []

        if title:
            lines.append(f"职位名称：{title}")
        if company:
            lines.append(f"公司名称：{company}")
        if location:
            lines.append(f"工作地点：{location}")
        if salary:
            lines.append(f"薪资：{salary}")

        lines.append("")

        if description:
            lines.append("【职位描述】")
            lines.append(description)
            lines.append("")

        if experience or education or skills:
            lines.append("【任职要求】")
            if experience:
                lines.append(f"- {experience}")
            if education:
                lines.append(f"- {education}")
            if skills:
                for skill in skills[:10]:
                    lines.append(f"- {skill}")
            lines.append("")

        return "\n".join(lines)
