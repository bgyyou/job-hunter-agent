"""
爬虫基类模块

BaseScraper 是所有爬虫的基类，提供通用功能：
- 网络请求
- 页面解析
- 错误处理
- 反爬策略集成
"""

import asyncio
import time
import random
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from pathlib import Path
import requests
from bs4 import BeautifulSoup
from loguru import logger
from fake_useragent import UserAgent

from .cookie_manager import CookieManager
from .rate_limiter import AdaptiveRateLimiter
from .human_simulator import HumanSimulator


class BaseScraper(ABC):
    """
    爬虫基类

    提供通用爬虫功能框架，包括：
    - 网络请求
    - User-Agent 轮换
    - Cookie 管理
    - 频率控制
    - 人类行为模拟
    - 错误处理和重试
    """

    def __init__(
        self,
        platform_name: str,
        base_url: str,
        cookie_dir: str = "data/cookies",
        state_dir: str = "data/scraper_states"
    ):
        """
        初始化爬虫

        Args:
            platform_name: 平台名称（如 "boss"、"liepin"）
            base_url: 平台基础 URL
            cookie_dir: Cookie 存储目录
            state_dir: 状态存储目录
        """
        self.platform_name = platform_name
        self.base_url = base_url
        self.ua = UserAgent()
        self.session = requests.Session()

        # 初始化组件
        self.cookie_manager = CookieManager(
            platform_name=platform_name,
            storage_dir=cookie_dir
        )
        self.rate_limiter = AdaptiveRateLimiter()
        self.human_simulator = HumanSimulator()

        # 状态管理
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.state_dir / f"{platform_name}.json"

        # 配置 Session
        self._configure_session()

        # 日志器
        self.logger = logger.bind(scraper=platform_name)

    def _configure_session(self):
        """配置 Session"""
        # 设置默认 Headers
        self.session.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        })

        # 加载 Cookie
        cookies = self.cookie_manager.load_cookies()
        if cookies:
            self.session.cookies.update(cookies)
            self.logger.debug(f"已加载 {len(cookies)} 个 Cookie")

    def _get_random_user_agent(self) -> str:
        """
        获取随机 User-Agent

        Returns:
            User-Agent 字符串
        """
        try:
            return self.ua.random
        except Exception:
            # 如果 fake_useragent 失败，使用备用列表
            fallback_ua = [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            ]
            return random.choice(fallback_ua)

    def _get_headers(self, custom_headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """
        获取请求 Headers

        Args:
            custom_headers: 自定义 Headers

        Returns:
            完整的 Headers
        """
        headers = self.session.headers.copy()
        headers["User-Agent"] = self._get_random_user_agent()

        if custom_headers:
            headers.update(custom_headers)

        return headers

    async def _request(
        self,
        method: str,
        url: str,
        **kwargs
    ) -> requests.Response:
        """
        发送 HTTP 请求（带重试和反爬）

        Args:
            method: HTTP 方法（GET/POST）
            url: 请求 URL
            **kwargs: 其他请求参数

        Returns:
            Response 对象

        Raises:
            Exception: 请求失败
        """
        # 应用频率限制
        await self.rate_limiter.wait()

        # 模拟人类行为
        await self.human_simulator.simulate_think_time()

        # 更新 Headers
        kwargs.setdefault("headers", {})
        kwargs["headers"] = self._get_headers(kwargs["headers"])

        # 添加 Referer
        if "Referer" not in kwargs["headers"]:
            kwargs["headers"]["Referer"] = self.base_url

        max_retries = kwargs.pop("max_retries", 3)
        timeout = kwargs.pop("timeout", 30)

        for attempt in range(max_retries):
            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    timeout=timeout,
                    **kwargs
                )

                # 保存 Cookie
                if response.cookies:
                    self.cookie_manager.save_cookies(dict(response.cookies))

                # 检查是否被反爬
                if self._detect_anti_bot(response):
                    self.logger.warning("检测到反爬机制")
                    # 记录失败，增加延迟
                    self.rate_limiter.record_failure()

                    # 等待更长时间后重试
                    await asyncio.sleep(random.uniform(30, 60))
                    continue

                # 请求成功，记录成功
                self.rate_limiter.record_success()

                return response

            except requests.exceptions.Timeout:
                self.logger.warning(f"请求超时 (尝试 {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    await asyncio.sleep(5)
                continue

            except requests.exceptions.RequestException as e:
                self.logger.error(f"请求失败: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(5)
                continue

            except Exception as e:
                self.logger.exception(f"未知错误: {e}")
                raise

        raise Exception(f"请求失败，已重试 {max_retries} 次")

    def _detect_anti_bot(self, response: requests.Response) -> bool:
        """
        检测是否被反爬

        Args:
            response: HTTP 响应

        Returns:
            是否被反爬
        """
        # 检查状态码
        if response.status_code == 403:
            return True

        # 检查响应内容
        content = response.text.lower()

        # 常见反爬检测关键词
        anti_bot_keywords = [
            "访问异常",
            "请先登录",
            "验证码",
            "captcha",
            "verify",
            "access denied",
            "forbidden",
            "blocked",
            "频繁访问",
            "频率限制",
        ]

        for keyword in anti_bot_keywords:
            if keyword in content:
                return True

        return False

    def _parse_html(self, html: str) -> BeautifulSoup:
        """
        解析 HTML

        Args:
            html: HTML 字符串

        Returns:
            BeautifulSoup 对象
        """
        return BeautifulSoup(html, "html.parser")

    async def _scroll_page(self):
        """
        模拟滚动页面（用于需要滚动加载的页面）
        注意：需要浏览器自动化，这里仅作为占位
        """
        await self.human_simulator.simulate_scroll()

    def _save_state(self, state: Dict[str, Any]):
        """
        保存状态

        Args:
            state: 状态数据
        """
        import json

        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            self.logger.debug("状态已保存")
        except Exception as e:
            self.logger.error(f"保存状态失败: {e}")

    def _load_state(self) -> Dict[str, Any]:
        """
        加载状态

        Returns:
            状态数据
        """
        import json

        if not self.state_file.exists():
            return {}

        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"加载状态失败: {e}")
            return {}

    @abstractmethod
    async def login(self, username: str, password: str) -> bool:
        """
        登录

        Args:
            username: 用户名
            password: 密码

        Returns:
            是否登录成功
        """
        pass

    @abstractmethod
    async def is_logged_in(self) -> bool:
        """
        检查是否已登录

        Returns:
            是否已登录
        """
        pass

    @abstractmethod
    async def search_jobs(
        self,
        keyword: str,
        location: Optional[str] = None,
        page: int = 1,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        搜索职位

        Args:
            keyword: 搜索关键词
            location: 地点
            page: 页码
            **kwargs: 其他搜索参数

        Returns:
            职位列表
        """
        pass

    @abstractmethod
    async def parse_job(self, job_url: str) -> Dict[str, Any]:
        """
        解析职位详情

        Args:
            job_url: 职位 URL

        Returns:
            职位详情
        """
        pass

    def _deduplicate_jobs(self, jobs: List[Dict[str, Any]], key: str = "job_id") -> List[Dict[str, Any]]:
        """
        职位去重

        Args:
            jobs: 职位列表
            key: 去重键

        Returns:
            去重后的职位列表
        """
        seen = set()
        unique_jobs = []

        for job in jobs:
            job_key = job.get(key)
            if job_key and job_key not in seen:
                seen.add(job_key)
                unique_jobs.append(job)

        removed = len(jobs) - len(unique_jobs)
        if removed > 0:
            self.logger.info(f"去重：移除了 {removed} 个重复职位")

        return unique_jobs

    def __repr__(self) -> str:
        return f"BaseScraper(platform={self.platform_name}, base_url={self.base_url})"