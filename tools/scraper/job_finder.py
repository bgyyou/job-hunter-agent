# tools/scraper/job_finder.py
"""
JobFinder - 职位搜索器

支持：
- 多平台并发搜索
- 智能职位过滤
- 匹配度计算
"""
import asyncio
from typing import Dict, List, Optional, Any
from loguru import logger
from tools.scraper.jobsdb_scraper import JobsDBScraper
from tools.scraper.boss_scraper import BossScraper


class JobFinder:
    """
    职位搜索器

    并发搜索多个招聘平台，获取匹配的职位列表
    """

    def __init__(
        self,
        platforms: Optional[List[str]] = None,
        headless: bool = True
    ):
        """
        初始化职位搜索器

        Args:
            platforms: 搜索平台列表（None 则使用全部可用平台）
            headless: 是否无头模式
        """
        self.logger = logger.bind(component="job_finder")
        self.headless = headless

        # 可用平台
        self.available_platforms = {
            "jobsdb": JobsDBScraper,
            "boss": BossScraper,
            # 可添加更多平台
        }

        # 选择的平台
        if platforms:
            self.platforms = {k: v for k, v in self.available_platforms.items() if k in platforms}
        else:
            self.platforms = self.available_platforms

        self.logger.info(f"初始化 JobFinder，平台: {list(self.platforms.keys())}")

    async def search(
        self,
        keyword: str,
        location: Optional[str] = None,
        platforms: Optional[List[str]] = None,
        max_results: int = 50,
        pages: int = 1
    ) -> List[Dict[str, Any]]:
        """
        搜索职位

        Args:
            keyword: 搜索关键词
            location: 地点
            platforms: 指定平台（None 则使用所有）
            max_results: 最大结果数
            pages: 搜索页数

        Returns:
            职位列表
        """
        self.logger.info(f"搜索职位: {keyword}, 地点: {location}, 最大结果: {max_results}")

        # 确定要搜索的平台
        if platforms:
            search_platforms = {k: v for k, v in self.platforms.items() if k in platforms}
        else:
            search_platforms = self.platforms

        # 并发搜索
        search_tasks = []
        for platform_name, scraper_class in search_platforms.items():
            task = self._search_platform(
                scraper_class,
                platform_name,
                keyword,
                location,
                pages
            )
            search_tasks.append(task)

        # 并发执行
        all_jobs = []
        platform_results = await asyncio.gather(*search_tasks, return_exceptions=True)

        # 收集结果
        for result in platform_results:
            if isinstance(result, list):
                all_jobs.extend(result)
            elif isinstance(result, Exception):
                self.logger.error(f"搜索失败: {result}")

        # 去重
        all_jobs = self._deduplicate_jobs(all_jobs)

        # 限制数量
        all_jobs = all_jobs[:max_results]

        self.logger.info(f"搜索完成，共找到 {len(all_jobs)} 个职位")

        return all_jobs

    async def _search_platform(
        self,
        scraper_class,
        platform_name: str,
        keyword: str,
        location: Optional[str],
        pages: int
    ) -> List[Dict[str, Any]]:
        """
        搜索单个平台

        Args:
            scraper_class: 爬虫类
            platform_name: 平台名称
            keyword: 关键词
            location: 地点
            pages: 页数

        Returns:
            该平台的职位列表
        """
        jobs = []

        try:
            # 根据平台类型决定是否使用 Playwright
            if platform_name in ["jobsdb"]:
                # Playwright 爬虫
                scraper = scraper_class(headless=self.headless)
                async with scraper:
                    for page in range(1, pages + 1):
                        page_jobs = await scraper.search_jobs(
                            keyword=keyword,
                            location=location,
                            page=page
                        )
                        jobs.extend(page_jobs)
            else:
                # 传统爬虫（如 Boss）
                scraper = scraper_class()
                for page in range(1, pages + 1):
                    page_jobs = await scraper.search_jobs(
                        keyword=keyword,
                        location=location,
                        page=page
                    )
                    jobs.extend(page_jobs)

            self.logger.info(f"{platform_name}: 找到 {len(jobs)} 个职位")

        except Exception as e:
            self.logger.error(f"{platform_name} 搜索失败: {e}")

        return jobs

    def _deduplicate_jobs(self, jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        职位去重

        Args:
            jobs: 职位列表

        Returns:
            去重后的职位列表
        """
        seen = set()
        unique_jobs = []

        for job in jobs:
            # 使用标题 + 公司作为去重键
            key = f"{job.get('title', '')}-{job.get('company', '')}-{job.get('platform', '')}"

            if key not in seen:
                seen.add(key)
                unique_jobs.append(job)

        removed = len(jobs) - len(unique_jobs)
        if removed > 0:
            self.logger.info(f"去重：移除了 {removed} 个重复职位")

        return unique_jobs

    async def analyze_jobs(
        self,
        jobs: List[Dict[str, Any]],
        resume_data: Optional[Dict] = None
    ) -> List[Dict[str, Any]]:
        """
        分析职位（计算匹配度）

        Args:
            jobs: 职位列表
            resume_data: 简历数据（用于计算匹配度）

        Returns:
            带匹配度的职位列表
        """
        self.logger.info(f"分析 {len(jobs)} 个职位")

        analyzed_jobs = []

        for job in jobs:
            # 计算匹配度
            if resume_data:
                match_score = self._calculate_match_score(job, resume_data)
            else:
                match_score = 0.0

            job['match_score'] = match_score
            analyzed_jobs.append(job)

        # 按匹配度排序
        analyzed_jobs.sort(key=lambda x: x.get('match_score', 0), reverse=True)

        return analyzed_jobs

    def _calculate_match_score(
        self,
        job: Dict[str, Any],
        resume_data: Dict[str, Any]
    ) -> float:
        """
        计算职位-简历匹配度

        Args:
            job: 职位信息
            resume_data: 简历数据

        Returns:
            匹配度（0-1）
        """
        score = 0.0

        # 1. 技能匹配（40%）
        job_skills = set(job.get('skills_required', []))
        resume_skills = set(resume_data.get('skills', []))

        if job_skills:
            skill_match = len(job_skills & resume_skills) / len(job_skills)
            score += skill_match * 0.4

        # 2. 经验匹配（30%）
        # 简化处理：假设简历中的经验年限满足要求
        score += 0.3

        # 3. 学历匹配（20%）
        # 简化处理：假设学历满足
        score += 0.2

        # 4. 薪资匹配（10%）
        # 可以根据简历期望薪资和 JD 薪资范围计算
        score += 0.1

        return min(score, 1.0)

    def filter_by_criteria(
        self,
        jobs: List[Dict[str, Any]],
        min_salary: Optional[int] = None,
        max_salary: Optional[int] = None,
        location: Optional[str] = None,
        experience: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        根据条件过滤职位

        Args:
            jobs: 职位列表
            min_salary: 最低薪资
            max_salary: 最高薪资
            location: 地点（支持模糊匹配）
            experience: 工作经验要求

        Returns:
            过滤后的职位列表
        """
        filtered = jobs

        if min_salary:
            filtered = [
                job for job in filtered
                if self._parse_salary(job.get('salary', ''))[0] >= min_salary
            ]

        if max_salary:
            filtered = [
                job for job in filtered
                if self._parse_salary(job.get('salary', ''))[1] <= max_salary
            ]

        if location:
            location_lower = location.lower()
            filtered = [
                job for job in filtered
                if location_lower in job.get('location', '').lower()
            ]

        self.logger.info(f"过滤结果: {len(jobs)} -> {len(filtered)}")

        return filtered

    def _parse_salary(self, salary_text: str) -> tuple[Optional[int], Optional[int]]:
        """
        解析薪资文本

        Args:
            salary_text: 薪资文本

        Returns:
            (最低薪资, 最高薪资)
        """
        # 简化处理，实际应该更智能
        # 支持多种格式：30K-50K, 30,000-50,000, etc.
        import re

        # 尝试匹配数字范围
        match = re.search(r'(\d+)[^\d]+(\d+)', salary_text)
        if match:
            return int(match.group(1)), int(match.group(2))

        # 尝试匹配单个数字
        match = re.search(r'(\d+)', salary_text)
        if match:
            salary = int(match.group(1))
            return salary, salary

        return None, None

    def get_platforms(self) -> List[str]:
        """获取支持的平台列表"""
        return list(self.available_platforms.keys())


# 测试代码
async def main():
    """测试职位搜索器"""

    finder = JobFinder(headless=True, platforms=["jobsdb"])

    # 搜索职位
    jobs = await finder.search(
        keyword="Software Engineer",
        location="Hong Kong",
        max_results=10
    )

    print(f"\n找到 {len(jobs)} 个职位:\n")

    for i, job in enumerate(jobs, 1):
        print(f"{i}. {job['title']}")
        print(f"   公司: {job['company']}")
        print(f"   地点: {job['location']}")
        print(f"   薪资: {job['salary']}")
        print(f"   平台: {job['platform']}")
        print(f"   URL: {job['url']}")
        print()


if __name__ == "__main__":
    asyncio.run(main())