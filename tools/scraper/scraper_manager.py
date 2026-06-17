# tools/scraper/scraper_manager.py
"""
爬虫管理器 - 统一管理多个招聘平台的爬虫
"""
import asyncio
from typing import Dict, List, Any, Optional
from loguru import logger

from .jobsdb_scraper import JobsDBScraper
from .boss_scraper import BossScraper
from .jd_analyzer_enhanced import JDAnalyzerEnhanced


class ScraperManager:
    """
    爬虫管理器

    统一管理多个招聘平台的爬虫：
    - JobsDB（优先）
    - Boss直聘
    - 猎聘
    """

    def __init__(self, llm_client=None):
        """
        初始化爬虫管理器

        Args:
            llm_client: LLM客户端（用于JD分析）
        """
        self.logger = logger.bind(component="scraper_manager")

        # 爬虫实例（按需初始化）
        self.scrapers = {
            "jobsdb": None,
            "boss": None,
            "liepin": None,
        }

        # JD分析器
        self.jd_analyzer = JDAnalyzerEnhanced(llm_client) if llm_client else None

    def get_supported_platforms(self) -> List[str]:
        """获取支持的平台列表"""
        return list(self.scrapers.keys())

    def get_platform_info(self, platform: str) -> Dict[str, Any]:
        """获取平台信息"""
        info = {
            "jobsdb": {
                "name": "JobsDB",
                "region": "Hong Kong",
                "has_playwright": True,
                "needs_cookie": False,
            },
            "boss": {
                "name": "Boss直聘",
                "region": "China",
                "has_playwright": False,
                "needs_cookie": True,
            },
            "liepin": {
                "name": "猎聘",
                "region": "China",
                "has_playwright": False,
                "needs_cookie": True,
            },
        }
        return info.get(platform, {})

    async def search_jobs(
        self,
        platform: str,
        keyword: str,
        location: Optional[str] = None,
        limit: int = 10,
        headless: bool = False,
        user_data_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        搜索职位

        Args:
            platform: 平台名称（jobsdb, boss, liepin）
            keyword: 搜索关键词
            location: 地点
            limit: 最多获取数量
            headless: 是否无头模式
            user_data_dir: Playwright用户数据目录

        Returns:
            搜索结果，包含：
                - success: 是否成功
                - jobs: 职位列表
                - error: 错误信息（如果有）
        """
        self.logger.info(f"开始搜索: 平台={platform}, 关键词={keyword}, 地点={location}")

        scraper = None
        try:
            # 获取爬虫实例
            scraper = await self._get_or_create_scraper(
                platform=platform,
                headless=headless,
                user_data_dir=user_data_dir,
            )

            if not scraper:
                return {
                    "success": False,
                    "jobs": [],
                    "error": f"不支持的平台: {platform}"
                }

            # 启动浏览器（仅适用于 PlaywrightScraper）
            if hasattr(scraper, 'start'):
                self.logger.info("正在启动浏览器...")
                await scraper.start()

            # 搜索职位
            jobs = []
            page = 1

            while len(jobs) < limit:
                try:
                    page_jobs = await scraper.search_jobs(
                        keyword=keyword,
                        location=location,
                        page=page,
                    )

                    if not page_jobs:
                        self.logger.info(f"第{page}页没有更多结果")
                        break

                    jobs.extend(page_jobs)
                    self.logger.info(f"第{page}页获取到 {len(page_jobs)} 个职位，总计 {len(jobs)}")

                    if len(page_jobs) < 10:
                        # 每页少于10个，可能已经是最后一页
                        break

                    page += 1

                    # 避免请求太快
                    await asyncio.sleep(1)

                except Exception as e:
                    self.logger.exception(f"第{page}页搜索失败: {e}")
                    break

            # 截取指定数量
            jobs = jobs[:limit]

            self.logger.info(f"搜索完成，共获取 {len(jobs)} 个职位")

            # 直接返回搜索页的职位信息，不跳转到详情页（更稳定）
            return {
                "success": True,
                "jobs": jobs,
                "count": len(jobs),
            }

        except Exception as e:
            self.logger.exception(f"搜索失败: {e}")
            return {
                "success": False,
                "jobs": [],
                "error": str(e),
            }
        finally:
            # 关闭浏览器
            if scraper and hasattr(scraper, 'close'):
                try:
                    self.logger.info("正在关闭浏览器...")
                    await scraper.close()
                except Exception as e:
                    self.logger.warning(f"关闭浏览器失败: {e}")

    async def _get_or_create_scraper(
        self,
        platform: str,
        headless: bool = False,
        user_data_dir: Optional[str] = None,
    ):
        """
        获取或创建爬虫实例

        Args:
            platform: 平台名称
            headless: 是否无头模式
            user_data_dir: Playwright用户数据目录

        Returns:
            爬虫实例
        """
        if platform == "jobsdb":
            # 总是创建新实例，使用持久化用户数据（保持登录状态）
            return JobsDBScraper(
                headless=headless,
                user_data_dir=user_data_dir,
                browser_type="msedge"  # 使用 Edge，兼容性更好
            )

        elif platform == "boss":
            if not self.scrapers["boss"]:
                self.scrapers["boss"] = BossScraper()
            return self.scrapers["boss"]

        elif platform == "liepin":
            # 猎聘爬虫暂未实现
            self.logger.warning("猎聘爬虫暂未实现")
            return None

        return None

    async def _get_job_detail(self, scraper, job: Dict[str, Any]) -> Dict[str, Any]:
        """
        获取职位详情（不同平台有不同实现）

        Args:
            scraper: 爬虫实例
            job: 职位数据

        Returns:
            增强的职位数据
        """
        # 基础信息
        job_detail = job.copy()

        # 如果有URL，尝试获取完整JD文本
        job_url = job.get("url", "")
        if job_url:
            try:
                job_detail["raw_text"] = await self._extract_jd_text(scraper, job_url)
            except Exception as e:
                self.logger.debug(f"获取JD文本失败: {e}")

        return job_detail

    async def _extract_jd_text(self, scraper, url: str) -> str:
        """
        从职位页面提取JD文本

        Args:
            scraper: 爬虫实例
            url: 职位URL

        Returns:
            JD文本
        """
        # 根据平台使用不同方法
        platform_name = getattr(scraper, "platform_name", "unknown")

        if platform_name == "jobsdb" and hasattr(scraper, "page"):
            # JobsDB使用Playwright
            try:
                await scraper.navigate(url, wait_for="body")
                await asyncio.sleep(2)

                # 获取页面内容
                page_content = await scraper.page.content()

                # 简单提取页面文本
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(page_content, "html.parser")
                text_parts = []

                # 提取职位描述
                desc_elem = soup.find(attrs={"data-automation": "jobDescription"})
                if desc_elem:
                    text_parts.append(desc_elem.get_text(strip=True, separator="\n"))

                # 提取其他内容
                body_text = soup.body.get_text(strip=True, separator="\n")
                if body_text and len(body_text) < 20000:
                    text_parts.append(body_text)

                return "\n" + "\n".join(text_parts)

            except Exception as e:
                self.logger.debug(f"JobsDB提取JD失败: {e}")

        # 默认返回空字符串
        return ""

    async def analyze_and_classify_jd(
        self,
        jd: Dict[str, Any],
        knowledge_base=None,
    ) -> Dict[str, Any]:
        """
        分析并分类JD，然后保存到知识库

        Args:
            jd: 职位数据
            knowledge_base: 知识库实例

        Returns:
            分析结果
        """
        result = {"success": False, "classification": None, "jd_id": None}

        try:
            if not self.jd_analyzer:
                result["error"] = "未设置LLM客户端，无法分析JD"
                return result

            # 构建JD文本
            jd_text = jd.get("raw_text", "")
            if not jd_text:
                jd_text = f"Title: {jd.get('title', '')}\nCompany: {jd.get('company', '')}\nDescription: {jd.get('description', '')}"

            # 分析JD
            jd_result = await self.jd_analyzer.parse_from_text(jd_text)

            if knowledge_base:
                # 自动分类
                classification = await knowledge_base.classify_jd(jd_result)

                # 保存到对应数据库
                knowledge_base.switch_database(classification["category"])

                jd_id = knowledge_base.add_jd({
                    "raw_text": jd_text,
                    "parsed_data": jd_result,
                    "source": "scraper",
                    "url": jd.get("url", ""),
                })

                result["jd_id"] = jd_id
                result["classification"] = classification

            result["success"] = True
            result["jd_result"] = jd_result

        except Exception as e:
            self.logger.exception(f"分析JD失败: {e}")
            result["error"] = str(e)

        return result

    async def close_all(self):
        """关闭所有爬虫实例"""
        for name, scraper in self.scrapers.items():
            if scraper and hasattr(scraper, "close"):
                try:
                    await scraper.close()
                except Exception as e:
                    self.logger.warning(f"关闭爬虫 {name} 失败: {e}")
