"""
JobsDBScraper - JobsDB 香港爬虫

功能：
- 搜索职位（支持关键词和时间范围）
- 解析职位详情
- 保存到数据库
"""
import re
import json
from typing import Dict, List, Optional, Any
from datetime import datetime
from pathlib import Path
from loguru import logger

from .base_scraper import BaseScraper
from .human_playwright_scraper import HumanPlaywrightScraper


class JobsDBScraper(BaseScraper):
    """
    JobsDB 香港爬虫

    使用 Playwright 进行浏览器自动化，模拟人类行为
    """

    def __init__(self, headless: bool = False, human_speed: float = 0.5,
                 user_data_dir: Optional[str] = "data/browser_profiles/jobsdb"):
        """
        初始化 JobsDBScraper

        Args:
            headless: 是否无头模式
            human_speed: 人类速度倍数
            user_data_dir: 浏览器持久化目录（v2.1 M2.5：默认 data/browser_profiles/jobsdb，
                           复用一次登录后的 cookie/会话，避免每次都被反爬识别）
        """
        super().__init__(
            platform_name="jobsdb",
            base_url="https://hk.jobsdb.com",
        )

        # Playwright 浏览器爬虫
        self.playwright_scraper: Optional[HumanPlaywrightScraper] = None
        self.headless = headless
        self.human_speed = human_speed
        self.user_data_dir = user_data_dir

    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self._init_playwright()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器退出"""
        await self._close_playwright()

    async def _init_playwright(self):
        """初始化 Playwright"""
        if not self.playwright_scraper:
            self.playwright_scraper = HumanPlaywrightScraper(
                platform_name="jobsdb",
                headless=self.headless,
                human_speed=self.human_speed,
                browser_type="msedge",
                user_data_dir=self.user_data_dir,
            )
            await self.playwright_scraper.start()

    async def _close_playwright(self):
        """关闭 Playwright"""
        if self.playwright_scraper:
            await self.playwright_scraper.close()
            self.playwright_scraper = None

    async def login(self, username: str = "", password: str = "") -> bool:
        """
        JobsDB 通常不需要登录即可浏览职位

        Args:
            username: 用户名（可选）
            password: 密码（可选）

        Returns:
            是否登录成功（对于 JobsDB 总是返回 True）
        """
        self.logger.info("JobsDB 不需要登录即可浏览职位")
        return True

    async def is_logged_in(self) -> bool:
        """
        检查是否已登录

        Returns:
            对于 JobsDB 总是返回 True（不需要登录）
        """
        return True

    async def search_jobs(
        self,
        keyword: str,
        location: Optional[str] = None,
        page: int = 1,
        posted_within: Optional[int] = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        搜索职位

        Args:
            keyword: 搜索关键词
            location: 地点（可选，JobsDB 主要是香港）
            page: 页码
            posted_within: 时间范围（天数）：1/3/7/14/30
            **kwargs: 其他参数

        Returns:
            职位列表
        """
        await self._init_playwright()

        self.logger.info(f"搜索 JobsDB: '{keyword}' 第 {page} 页")

        try:
            # 构造搜索 URL
            search_keyword = keyword.replace(' ', '-')
            search_url = f"{self.base_url}/{search_keyword}-jobs"

            params = []
            if page > 1:
                params.append(f"page={page}")
            if posted_within:
                params.append(f"daterange={posted_within}")
            if params:
                search_url += "?" + "&".join(params)

            self.logger.info(f"访问: {search_url}")

            # 使用 Playwright 访问
            await self.playwright_scraper.human_navigate(search_url)
            await self.playwright_scraper.human_read_page(min_seconds=2.0, max_seconds=4.0)

            # 保存调试信息
            await self.playwright_scraper.take_screenshot("jobsdb_search_result.png")

            # 提取职位链接
            jobs = await self._extract_jobs_from_page()

            self.logger.info(f"找到 {len(jobs)} 个职位")

            return jobs

        except Exception as e:
            self.logger.exception(f"搜索失败: {e}")
            return []

    async def _extract_jobs_from_page(self) -> List[Dict[str, Any]]:
        """从当前页面提取职位链接"""
        jobs = []

        try:
            # 获取页面内容
            page_content = await self.playwright_scraper.page.content()

            # 保存 HTML 调试
            debug_dir = Path("data")
            debug_dir.mkdir(parents=True, exist_ok=True)
            (debug_dir / "jobsdb_debug_page.html").write_text(page_content, encoding="utf-8")

            # 提取职位链接
            all_links = await self.playwright_scraper.page.query_selector_all("a[href]")
            job_urls = []

            for link in all_links:
                href = await link.get_attribute("href") or ""
                if href and ("/job/" in href or "-job-" in href):
                    full_url = href if href.startswith("http") else self.base_url + href
                    if full_url not in job_urls:
                        job_urls.append(full_url)

            self.logger.info(f"找到 {len(job_urls)} 个职位链接")

            # 从链接创建职位对象
            for idx, job_url in enumerate(job_urls[:30]):  # 最多返回 30 个
                try:
                    # 从 URL 提取 job_id
                    job_id = self._extract_job_id(job_url)

                    job = {
                        "platform": "jobsdb",
                        "job_id": job_id,
                        "url": job_url,
                        "title": f"职位 {idx + 1}",
                        "company": "",
                        "location": "香港",
                        "description": "",
                        "scraped_at": datetime.now().isoformat()
                    }
                    jobs.append(job)

                except Exception as e:
                    self.logger.debug(f"处理链接失败: {e}")

        except Exception as e:
            self.logger.exception(f"提取职位失败: {e}")

        return jobs

    def _extract_job_id(self, url: str) -> str:
        """从 URL 提取职位 ID"""
        match = re.search(r"/job/(\d+)", url)
        if match:
            return match.group(1)
        # 备用方法
        match = re.search(r"-job-(\d+)", url)
        if match:
            return match.group(1)
        return url.split("/")[-1].split("?")[0]

    async def parse_job(self, job_url: str) -> Dict[str, Any]:
        """
        解析职位详情

        Args:
            job_url: 职位 URL

        Returns:
            职位详情字典
        """
        await self._init_playwright()

        try:
            self.logger.info(f"获取职位详情: {job_url}")

            await self.playwright_scraper.human_navigate(job_url)
            await self.playwright_scraper.human_read_page(min_seconds=3.0, max_seconds=6.0)

            # 获取页面文本
            page_text = await self.playwright_scraper.page.inner_text("body")

            # 提取信息
            job_detail = {
                "platform": "jobsdb",
                "job_id": self._extract_job_id(job_url),
                "url": job_url,
                "title": self._extract_title(page_text),
                "company": self._extract_company(page_text),
                "location": "香港",
                "salary_min": None,
                "salary_max": None,
                "salary_str": self._extract_salary(page_text),
                "requirements": page_text,
                "skills_required": self._extract_skills(page_text),
                "description": page_text,
                "raw_text": page_text,
                "posted_date": datetime.now().isoformat(),
                "scraped_at": datetime.now().isoformat(),
                "days_old": self._extract_days_old(page_text)
            }

            # 解析薪资
            salary_str = job_detail.get("salary_str", "")
            if salary_str:
                min_salary, max_salary = self._parse_salary(salary_str)
                job_detail["salary_min"] = min_salary
                job_detail["salary_max"] = max_salary

            self.logger.info(f"成功解析职位: {job_detail['title']}")

            return job_detail

        except Exception as e:
            self.logger.exception(f"解析职位失败: {e}")
            return {}

    async def get_job_detail(self, job_url: str) -> Dict[str, Any]:
        """
        获取职位详情（兼容旧接口）

        Args:
            job_url: 职位 URL

        Returns:
            职位详情
        """
        return await self.parse_job(job_url)

    def _extract_title(self, raw_text: str) -> str:
        """从原始文本提取标题"""
        lines = raw_text.split('\n')
        for i, line in enumerate(lines):
            line = line.strip()
            if line == "View all jobs" and i > 1:
                return lines[i - 2].strip()
        for line in lines:
            line = line.strip()
            if line and len(line) > 5 and len(line) < 100:
                return line
        return "未知职位"

    def _extract_company(self, raw_text: str) -> str:
        """从原始文本提取公司名"""
        lines = raw_text.split('\n')
        for i, line in enumerate(lines):
            line = line.strip()
            if line == "View all jobs" and i > 0:
                return lines[i - 1].strip()
        return ""

    def _extract_salary(self, raw_text: str) -> str:
        """从原始文本提取薪资"""
        salary_patterns = [
            r"HK\$[\d,]+\s*-\s*HK\$[\d,]+",
            r"HK\$[\d,]+\s*to\s*HK\$[\d,]+",
            r"\$[\d,]+\s*-\s*\$[\d,]+",
            r"[\d,]+\s*-\s*[\d,]+\s*K",
        ]
        for pattern in salary_patterns:
            match = re.search(pattern, raw_text)
            if match:
                return match.group(0)
        return ""

    def _parse_salary(self, salary_str: str) -> tuple:
        """解析薪资字符串"""
        try:
            numbers = re.findall(r'[\d,]+', salary_str)
            if len(numbers) >= 2:
                min_val = int(numbers[0].replace(',', ''))
                max_val = int(numbers[1].replace(',', ''))
                if 'K' in salary_str or 'k' in salary_str:
                    min_val *= 1000
                    max_val *= 1000
                # 转换为 K 为单位
                return min_val // 1000, max_val // 1000
            elif len(numbers) == 1:
                val = int(numbers[0].replace(',', ''))
                if 'K' in salary_str or 'k' in salary_str:
                    val *= 1000
                return val // 1000, val // 1000
        except:
            pass
        return None, None

    def _extract_skills(self, raw_text: str) -> List[str]:
        """从原始文本提取技能"""
        skills = []
        common_skills = [
            "Python", "Java", "JavaScript", "C++", "C#", "Go", "Rust",
            "SQL", "MongoDB", "Redis", "PostgreSQL", "MySQL",
            "React", "Vue", "Angular", "Node.js",
            "AWS", "Azure", "GCP", "Docker", "Kubernetes",
            "Machine Learning", "ML", "AI", "Deep Learning", "NLP",
            "Data Science", "Data Analysis", "ETL",
            "Project Management", "Agile", "Scrum", "Product Manager"
        ]
        for skill in common_skills:
            if skill.lower() in raw_text.lower():
                skills.append(skill)
        return list(set(skills))

    def _extract_days_old(self, raw_text: str) -> Optional[int]:
        """从原始文本提取发布天数"""
        match = re.search(r"Posted (\d+)d\+? ago", raw_text)
        if match:
            return int(match.group(1))
        match = re.search(r"Posted (\d+)w ago", raw_text)
        if match:
            return int(match.group(1)) * 7
        if "Posted yesterday" in raw_text:
            return 1
        if "Posted today" in raw_text:
            return 0
        match = re.search(r"(\d+)d\+?\s+ago", raw_text.lower())
        if match:
            return int(match.group(1))
        return None

    async def close(self):
        """关闭爬虫"""
        await self._close_playwright()

    def __repr__(self) -> str:
        return f"JobsDBScraper(headless={self.headless}, speed={self.human_speed}x)"

