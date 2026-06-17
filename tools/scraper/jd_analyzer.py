# tools/scraper/jd_analyzer.py
"""
JD 分析器 - 深度分析职位描述，提取核心要求、隐性要求和关键词
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


class JDAnalyzer:
    """JD 分析器"""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        """
        初始化 JD 分析器

        Args:
            llm_client: LLM 客户端（可选，不传则使用规则分析）
        """
        self.llm_client = llm_client
        self.logger = logger.bind(component="jd_analyzer")

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

        # 常见职位关键词
        self.tech_keywords = {
            "backend": ["Python", "Java", "Go", "Node.js", "后端", "微服务", "API"],
            "frontend": ["React", "Vue", "Angular", "TypeScript", "前端", "JavaScript"],
            "fullstack": ["全栈", "前后端", "Full Stack"],
            "data": ["Python", "SQL", "机器学习", "数据分析", "Data"],
            "devops": ["Docker", "Kubernetes", "CI/CD", "运维", "DevOps"],
            "mobile": ["iOS", "Android", "Flutter", "React Native", "移动端"],
            "ai": ["机器学习", "深度学习", "NLP", "AI", "LLM", "大模型"]
        }

        # 隐性要求关键词
        self.implicit_patterns = {
            "leadership": ["带领", "管理", "负责", "主导", "Leader", "Lead"],
            "teamwork": ["协作", "团队合作", "沟通", "Cross-functional"],
            "problem_solving": ["解决", "挑战", "优化", "性能", "问题"],
            "learning": ["学习", "快速", "新技术", "适应"],
            "pressure": ["压力", " deadline ", "紧张", "加班"],
            "english": ["英文", "English", "英语"]
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
        从文本分析 JD

        Args:
            text: JD 文本

        Returns:
            分析结果
        """
        self.logger.info("开始分析 JD")

        # 提取基本信息
        title = self._extract_title(text)
        company = self._extract_company(text)
        location = self._extract_location(text)
        salary_range = self._extract_salary(text)

        # 提取要求
        core_requirements = self._extract_core_requirements(text)
        preferred_requirements = self._extract_preferred_requirements(text)

        # 使用 LLM 进行深度分析（如果有）
        if self.llm_client:
            try:
                deep_analysis = await self._analyze_with_llm(text)

                # 合并结果，LLM 结果优先
                implicit_requirements = deep_analysis.get("implicit_requirements", "")
                keywords = deep_analysis.get("keywords", [])

                # 如果 LLM 提取的核心要求更详细，使用 LLM 的结果
                if len(deep_analysis.get("core_requirements", [])) > len(core_requirements):
                    core_requirements = deep_analysis["core_requirements"]

            except Exception as e:
                self.logger.warning(f"LLM 分析失败，使用规则分析: {e}")
                implicit_requirements = self._extract_implicit_requirements(text)
                keywords = self._extract_keywords(text)
        else:
            implicit_requirements = self._extract_implicit_requirements(text)
            keywords = self._extract_keywords(text)

        return {
            "title": title,
            "company": company,
            "location": location,
            "salary_range": salary_range,
            "core_requirements": core_requirements,
            "preferred_requirements": preferred_requirements,
            "implicit_requirements": implicit_requirements,
            "keywords": keywords,
            "raw_text": text
        }

    async def _analyze_with_llm(self, jd_text: str) -> Dict[str, Any]:
        """
        使用 LLM 深度分析 JD

        Args:
            jd_text: JD 文本

        Returns:
            分析结果
        """
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

            # 猎聘
            elif platform == "liepin":
                return await self._fetch_liepin_jd(url)

            # 智联招聘
            elif platform == "zhaopin":
                return await self._fetch_zhaopin_jd(url)

            # 前程无忧
            elif platform == "51job":
                return await self._fetch_51job_jd(url)

            # 拉勾
            elif platform == "lagou":
                return await self._fetch_lagou_jd(url)

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
        """
        从 Boss 直聘获取 JD

        Args:
            url: JD URL

        Returns:
            JD 文本
        """
        try:
            # 使用 BossScraper 获取职位详情
            scraper = self._scrapers.get("boss")
            if not scraper:
                # 创建新实例
                scraper = BossScraper()
                self._scrapers["boss"] = scraper

            # 获取职位详情
            job_detail = await scraper.parse_job(url)

            if not job_detail:
                # 如果爬虫失败，尝试通用方法
                return await self._fetch_generic_jd(url)

            # 构建标准化的 JD 文本格式
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

    async def _fetch_liepin_jd(self, url: str) -> str:
        """
        从猎聘获取 JD

        Args:
            url: JD URL

        Returns:
            JD 文本
        """
        return await self._fetch_generic_jd(url)

    async def _fetch_zhaopin_jd(self, url: str) -> str:
        """
        从智联招聘获取 JD

        Args:
            url: JD URL

        Returns:
            JD 文本
        """
        return await self._fetch_generic_jd(url)

    async def _fetch_51job_jd(self, url: str) -> str:
        """
        从前程无忧获取 JD

        Args:
            url: JD URL

        Returns:
            JD 文本
        """
        return await self._fetch_generic_jd(url)

    async def _fetch_lagou_jd(self, url: str) -> str:
        """
        从拉勾获取 JD

        Args:
            url: JD URL

        Returns:
            JD 文本
        """
        return await self._fetch_generic_jd(url)

    async def _fetch_jobsdb_jd(self, url: str) -> str:
        """
        从 JobsDB 获取 JD

        Args:
            url: JD URL

        Returns:
            JD 文本
        """
        self.logger.info("使用 Playwright 获取 JobsDB JD")

        try:
            # 使用 Playwright 爬虫
            scraper_class = self._playwright_scrapers.get("jobsdb")
            if not scraper_class:
                self.logger.error("JobsDB scraper class not found")
                return ""

            # 创建并启动爬虫
            scraper = scraper_class(headless=True)  # 使用无头模式

            # 使用上下文管理器自动清理
            async with scraper:
                # 检查登录状态
                if not await scraper.is_logged_in():
                    self.logger.warning("需要登录，但无头模式下无法处理")
                    # 尝试获取页面内容，可能不需要登录
                    pass

                # 获取 JD 文本
                jd_text = await scraper.get_jd_text(url)

                if jd_text:
                    self.logger.info(f"成功获取 JobsDB JD: {len(jd_text)} 字符")
                    return jd_text
                else:
                    self.logger.warning("未能够获取 JD 文本")
                    return ""

        except Exception as e:
            self.logger.error(f"Playwright 获取 JD 失败: {e}")
            return ""

    async def _fetch_generic_jd(self, url: str) -> str:
        """
        通用 JD 获取方法（适用于未知或未实现特定爬虫的平台）

        Args:
            url: JD URL

        Returns:
            JD 文本
        """
        self.logger.info(f"使用通用方法获取 JD: {url}")

        try:
            response = self._session.get(url, timeout=15)
            response.raise_for_status()

            # 解析 HTML
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

            # 获取职位描述（最关键的部分）
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
        """
        按选择器列表依次尝试提取文本

        Args:
            soup: BeautifulSoup 对象
            selectors: CSS 选择器列表

        Returns:
            提取的文本
        """
        for selector in selectors:
            elem = soup.select_one(selector)
            if elem:
                text = elem.get_text(strip=True)
                if text and len(text) < 200:  # 避免获取到过长的内容
                    return text
        return ""

    def _extract_description(self, soup: BeautifulSoup) -> str:
        """
        提取职位描述

        Args:
            soup: BeautifulSoup 对象

        Returns:
            职位描述文本
        """
        # 尝试多种选择器模式
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
                if len(text) > 50:  # 确保有内容
                    return text

        # 如果都没找到，尝试获取页面主要内容
        # 移除不需要的标签
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        # 获取页面文本
        text = soup.get_text(separator="\n", strip=True)

        # 简单清洗：只保留包含常见 JD 关键词的段落
        keywords = ["职责", "要求", "要求", "描述", "任职", "岗位", "技能", "experience", "requirement", "responsibility"]
        paragraphs = text.split("\n")
        filtered = [p for p in paragraphs if any(kw in p.lower() for kw in keywords) or len(p) > 20]

        return "\n".join(filtered[:20])  # 限制长度

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
        """
        将提取的信息格式化为标准 JD 文本

        Args:
            title: 职位名称
            company: 公司名称
            location: 工作地点
            salary: 薪资
            experience: 工作经验
            education: 学历
            description: 职位描述
            skills: 技能列表

        Returns:
            格式化的 JD 文本
        """
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

        lines.append("")  # 空行

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
                for skill in skills[:10]:  # 限制数量
                    lines.append(f"- {skill}")
            lines.append("")

        return "\n".join(lines)

    def _extract_title(self, text: str) -> str:
        """提取职位名称"""
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

        return "未知职位"

    def _extract_company(self, text: str) -> str:
        """提取公司名称"""
        patterns = [
            r'公司名称[：:]\s*(.+?)(?:\n|$)',
            r'公司[：:]\s*(.+?)(?:\n|$)',
            r'Company[：:]\s*(.+?)(?:\n|$)'
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return "未知公司"

    def _extract_location(self, text: str) -> str:
        """提取工作地点"""
        patterns = [
            r'工作地点[：:]\s*(.+?)(?:\n|$)',
            r'地点[：:]\s*(.+?)(?:\n|$)',
            r'Location[：:]\s*(.+?)(?:\n|$)'
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return "未知"

    def _extract_salary(self, text: str) -> str:
        """提取薪资范围"""
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

        return "面议"

    def _extract_core_requirements(self, text: str) -> List[str]:
        """提取核心要求"""
        requirements = []

        # 首先尝试英文格式
        requirement_patterns = [
            r'Requirements[:\s]*\n(.*?)(?=\n\n|\n\d+\.|\nPreferred|\nQualifications)',
            r'Qualifications[:\s]*\n(.*?)(?=\n\n|\n\d+\.|\nPreferred)'
        ]

        for pattern in requirement_patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                section_text = match.group(1)

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

                if requirements:
                    break

        # 尝试中文格式 - 使用更简单的方法
        if not requirements:
            # 查找 【任职要求】 章节
            for keyword in ['【任职要求】', '【职位要求】', '【岗位要求】', '【要求】', '任职要求', '职位要求', '岗位要求']:
                idx = text.find(keyword)
                if idx >= 0:
                    # 提取到下一个章节的内容
                    end_patterns = ['【加分项】', '【优先】', '【职责】', '【职位描述】', '加分项', '职责', '职位描述']
                    end_idx = len(text)
                    for end_pattern in end_patterns:
                        temp_idx = text.find(end_pattern, idx + len(keyword))
                        if temp_idx >= 0 and temp_idx < end_idx:
                            end_idx = temp_idx

                    section_text = text[idx + len(keyword):end_idx].strip()

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

                    if requirements:
                        break

        return requirements[:10]

    def _extract_preferred_requirements(self, text: str) -> List[str]:
        """提取加分项"""
        requirements = []

        patterns = [
            # 中文格式 - 【加分项】章节
            r'[【[]加分项[】]].*?\n(.*?)(?=\n\n|\n[【[]|\n[一二三四五六七八九十])',
            r'[【[]优先[】]].*?\n(.*?)(?=\n\n|\n[【[]|\n[一二三四五六七八九十])',
            # 英文格式
            r'[【[]Preferred[【[]][\s]*(?:Qualifications|Requirements)?[】]].*?\n(.*?)(?=\n\n|\n[【[]|\n\d+\.)',
            r'Preferred\s*(?:Qualifications|Requirements)?[：:].*?\n(.*?)(?=\n\n|\n[【[]|\n\d+\.|\n[A-Z][a-z]+:)'
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                section_text = match.group(1)
                # 提取带序号的要求（支持中文数字和阿拉伯数字）
                numbered_items = re.findall(r'[一二三四五六七八九十\d][\.、]\s*(.+?)(?=\n|$)', section_text)
                numbered_items += re.findall(r'[-]\s*(.+?)(?=\n|$)', section_text)
                for item in numbered_items:
                    item = item.strip()
                    if len(item) > 3 and item not in requirements:
                        requirements.append(item)

                if requirements:
                    break

        return requirements[:5]

    def _extract_implicit_requirements(self, text: str) -> str:
        """提取隐性要求"""
        implicit = []

        for trait, patterns in self.implicit_patterns.items():
            found = []
            for pattern in patterns:
                if pattern.lower() in text.lower():
                    found.append(pattern)

            if found:
                implicit.append(f"{trait}: {', '.join(found)}")

        return "\n".join(implicit) if implicit else "无明显隐性要求"

    def _extract_keywords(self, text: str) -> List[str]:
        """提取岗位关键词"""
        keywords = set()

        # 提取技术关键词
        text_lower = text.lower()
        for tech_list in self.tech_keywords.values():
            for tech in tech_list:
                if tech.lower() in text_lower:
                    keywords.add(tech)

        # 提取常见的职位关键词
        common_keywords = [
            "架构", "设计", "开发", "测试", "运维", "产品", "项目管理",
            "沟通", "协作", "团队", "优化", "性能", "安全", "算法",
            "数据", "机器学习", "人工智能", "云", "大数据", "微服务"
        ]

        for keyword in common_keywords:
            if keyword in text:
                keywords.add(keyword)

        return sorted(list(keywords))[:15]