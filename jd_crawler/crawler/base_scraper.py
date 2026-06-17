"""
基础爬虫类 - 使用 Playwright + Edge
"""
import asyncio
import random
from pathlib import Path
from typing import Optional
from loguru import logger
from playwright.async_api import async_playwright, BrowserContext, Page

from .edge_profile import setup_edge_profile


class BaseScraper:
    """基础爬虫类"""

    def __init__(
        self,
        headless: bool = False,
        human_speed: float = 0.5,  # 比人类慢一半，更安全
    ):
        self.headless = headless
        self.human_speed = human_speed
        self.playwright = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.user_data_dir = setup_edge_profile()

    async def start(self):
        """启动浏览器"""
        logger.info("Starting Microsoft Edge...")

        self.playwright = await async_playwright().start()

        # 启动持久化上下文（不使用 channel 参数）
        launch_options = {
            "headless": self.headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-features=IsolateOrigins,site-per-process",
                "--window-size=1920,1080",
            ],
            "viewport": {"width": 1920, "height": 1080},
            "locale": "zh-CN",
            "timezone_id": "Asia/Shanghai",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
        }

        logger.info(f"Using Profile: {self.user_data_dir}")

        # 使用 chromium 引擎启动持久化上下文（会自动找到 Edge）
        self.context = await self.playwright.chromium.launch_persistent_context(
            str(self.user_data_dir),
            **launch_options
        )

        # 获取页面（或创建新页面）
        if self.context.pages:
            self.page = self.context.pages[0]
        else:
            self.page = await self.context.new_page()

        # 隐藏自动化特征
        await self._hide_automation_features()

        logger.success("Edge 启动完成")

    async def _hide_automation_features(self):
        """隐藏自动化特征"""
        await self.page.add_init_script("""
            // 移除 navigator.webdriver
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });

            // 移除自动化相关属性
            delete window.__playwright;
            delete window.__pw_manual;
            delete window.__pw_bindingName;

            // 模拟真实插件
            Object.defineProperty(navigator, 'plugins', {
                get: () => [
                    { description: 'PDF Viewer', name: 'Chrome PDF Plugin' },
                    { description: 'PDF Viewer', name: 'Chrome PDF Viewer' }
                ]
            });

            // 模拟语言
            Object.defineProperty(navigator, 'languages', {
                get: () => ['zh-CN', 'zh', 'en-US', 'en']
            });

            // 模拟 chrome 对象
            window.chrome = { runtime: {} };

            // 覆盖权限查询
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications'
                    ? Promise.resolve({ state: Notification.permission })
                    : originalQuery(parameters)
            );

            // 模拟平台
            Object.defineProperty(navigator, 'platform', {
                get: () => 'Win32'
            });
        """)

    async def human_navigate(self, url: str):
        """类人方式导航"""
        logger.info(f"导航到: {url}")

        # 随机小停顿
        await asyncio.sleep(random.uniform(0.3, 0.8) * self.human_speed)

        await self.page.goto(url, wait_until="domcontentloaded", timeout=60000)

        # 等待页面稳定
        await asyncio.sleep(random.uniform(1.0, 2.0) * self.human_speed)

        # 轻微滚动模拟阅读
        scroll_amount = random.randint(50, 150)
        await self.page.evaluate(f"window.scrollBy(0, {scroll_amount})")
        await asyncio.sleep(random.uniform(0.3, 0.6) * self.human_speed)
        await self.page.evaluate(f"window.scrollBy(0, -{scroll_amount // 2})")

    async def human_read(self, min_seconds: float = 2.0, max_seconds: float = 5.0):
        """模拟人类阅读"""
        read_time = random.uniform(min_seconds, max_seconds) * self.human_speed
        logger.debug(f"模拟阅读: {read_time:.1f}秒")

        # 边读边随机滚动
        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < read_time:
            scroll = random.randint(-100, 200)
            await self.page.evaluate(f"window.scrollBy(0, {scroll})")
            await asyncio.sleep(random.uniform(0.5, 1.5) * self.human_speed)

    async def close(self):
        """关闭浏览器"""
        logger.info("关闭浏览器...")
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()
        logger.success("浏览器已关闭")

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
