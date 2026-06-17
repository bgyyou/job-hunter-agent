# tools/scraper/playwright_scraper.py
"""
Playwright 基础爬虫 - 支持动态加载的网页

使用 Playwright 实现浏览器自动化，解决 JavaScript 动态加载问题
"""
from typing import Dict, List, Optional, Any
from pathlib import Path
from abc import ABC, abstractmethod
from loguru import logger
from playwright.async_api import async_playwright, Browser, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError
import asyncio


class PlaywrightScraper(ABC):
    """
    Playwright 基础爬虫

    支持动态加载的网页，解决传统 HTTP 请求无法获取 JavaScript 渲染内容的问题
    """

    def __init__(
        self,
        platform_name: str,
        headless: bool = False,
        user_data_dir: Optional[str] = None,
        browser_type: str = "msedge"
    ):
        """
        初始化爬虫

        Args:
            platform_name: 平台名称
            headless: 是否无头模式运行（不显示浏览器窗口）
            user_data_dir: 用户数据目录（用于保存登录状态）
            browser_type: 浏览器类型 (chromium, firefox, webkit, msedge)
        """
        self.platform_name = platform_name
        self.headless = headless
        self.user_data_dir = user_data_dir
        self.browser_type = browser_type
        self.logger = logger.bind(scraper=platform_name)

        # 不使用持久化上下文，避免启动问题
        # 如果没有指定用户数据目录，使用 None
        if not self.user_data_dir:
            self.user_data_dir = None
        else:
            self.logger.info(f"使用用户数据目录: {self.user_data_dir}")

        # Playwright 实例
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.close()

    async def start(self):
        """启动浏览器"""
        self.logger.info(f"启动 {self.platform_name} 爬虫 (浏览器: {self.browser_type})...")

        self.playwright = await async_playwright().start()

        # 获取浏览器实例
        if self.browser_type == "msedge":
            browser_launcher = self.playwright.chromium
            launch_options = {
                "headless": self.headless,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--disable-infobars",
                    "--disable-extensions",
                    "--disable-popup-blocking",
                    "--disable-notifications",
                    "--window-size=1920,1080",
                    "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
                ],
                "channel": "msedge"  # 使用 Edge 通道
            }
        else:
            browser_launcher = getattr(self.playwright, self.browser_type, self.playwright.chromium)
            launch_options = {
                "headless": self.headless,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-infobars",
                    "--disable-extensions",
                    "--disable-popup-blocking",
                    "--disable-notifications",
                    "--window-size=1920,1080",
                    "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                ]
            }

        # 如果有用户数据目录，使用持久化上下文
        if self.user_data_dir:
            user_data_path = Path(self.user_data_dir)
            user_data_path.mkdir(parents=True, exist_ok=True)

            # Edge 持久化不需要 channel
            launch_opts = {
                "headless": self.headless,
                "args": launch_options["args"],
                "viewport": {"width": 1920, "height": 1080},
                "locale": "zh-CN",
                "timezone_id": "Asia/Shanghai",
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
            }

            self.context = await browser_launcher.launch_persistent_context(
                str(user_data_path),
                **launch_opts
            )
        else:
            # 启动浏览器和上下文
            if self.browser_type == "msedge":
                # 使用 channel 参数指定 Edge
                self.browser = await browser_launcher.launch(**launch_options)
            else:
                self.browser = await browser_launcher.launch(**launch_options)

            user_agent_str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            if self.browser_type == "msedge":
                user_agent_str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0"

            self.context = await self.browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=user_agent_str,
                locale="zh-HK",
                timezone_id="Asia/Hong_Kong",
                permissions=["geolocation"],
                geolocation={"latitude": 22.3193, "longitude": 114.1694},  # 香港
            )

        # 创建页面
        self.page = await self.context.new_page()

        # 隐藏自动化特征 - 在页面创建后立即执行
        await self.page.add_init_script("""
            // 移除 navigator.webdriver
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });

            // 移除自动化相关的属性
            delete window.__playwright;
            delete window.__pw_manual;
            delete window.__pw_bindingName;

            // 模拟真实的插件
            Object.defineProperty(navigator, 'plugins', {
                get: () => [
                    { description: 'PDF Viewer', name: 'Chrome PDF Plugin' },
                    { description: 'PDF Viewer', name: 'Chrome PDF Viewer' }
                ]
            });

            // 模拟真实的语言
            Object.defineProperty(navigator, 'languages', {
                get: () => ['zh-CN', 'zh', 'en-US', 'en']
            });

            // 模拟 chrome 对象
            window.chrome = {
                runtime: {}
            };

            // 覆盖权限查询
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications'
                    ? Promise.resolve({ state: Notification.permission })
                    : originalQuery(parameters)
            );

            // 模拟屏幕信息
            Object.defineProperty(navigator, 'platform', {
                get: () => 'Win32'
            });
        """)

        # 设置默认超时
        self.page.set_default_timeout(120000)  # 120 秒

        self.logger.info(f"{self.platform_name} 爬虫启动成功")

    async def _hide_automation_features(self):
        """隐藏自动化特征"""
        # 移除 navigator.webdriver
        await self.page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            Object.defineProperty(navigator, 'languages', {
                get: () => ['zh-HK', 'zh', 'en-US', 'en']
            });
            window.chrome = {
                runtime: {}
            };
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );
        """)

    async def close(self):
        """关闭浏览器"""
        self.logger.info(f"关闭 {self.platform_name} 爬虫...")

        if self.page:
            await self.page.close()

        if self.context:
            await self.context.close()

        if self.browser:
            await self.browser.close()

        if self.playwright:
            await self.playwright.stop()

        self.logger.info(f"{self.platform_name} 爬虫已关闭")

    async def navigate(self, url: str, wait_for: Optional[str] = None) -> bool:
        """
        导航到指定 URL

        Args:
            url: 目标 URL
            wait_for: 等待的 CSS 选择器，等待元素出现

        Returns:
            是否成功导航
        """
        try:
            self.logger.info(f"导航到: {url}")

            await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # 等待指定元素
            if wait_for:
                await self.page.wait_for_selector(wait_for, timeout=10000)

            # 等待页面稳定
            await asyncio.sleep(1)

            return True

        except PlaywrightTimeoutError:
            self.logger.warning(f"导航超时: {url}")
            return False
        except Exception as e:
            self.logger.error(f"导航失败: {e}")
            return False

    async def get_page_text(self) -> str:
        """
        获取页面文本

        Returns:
            页面文本内容
        """
        try:
            return await self.page.inner_text("body")
        except Exception as e:
            self.logger.error(f"获取页面文本失败: {e}")
            return ""

    async def get_page_html(self) -> str:
        """
        获取页面 HTML

        Returns:
            页面 HTML 内容
        """
        try:
            return await self.page.content()
        except Exception as e:
            self.logger.error(f"获取页面 HTML 失败: {e}")
            return ""

    async def wait_for_content(self, min_length: int = 100, timeout: int = 30000) -> bool:
        """
        等待页面加载足够的内容

        Args:
            min_length: 最小文本长度
            timeout: 超时时间（毫秒）

        Returns:
            是否加载成功
        """
        start_time = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - start_time < timeout / 1000:
            text = await self.get_page_text()
            if len(text) >= min_length:
                self.logger.debug(f"页面内容已加载: {len(text)} 字符")
                return True

            await asyncio.sleep(0.5)

        self.logger.warning(f"等待页面内容超时")
        return False

    async def scroll_to_bottom(self, max_scrolls: int = 10) -> None:
        """
        滚动到页面底部（用于懒加载）

        Args:
            max_scrolls: 最大滚动次数
        """
        self.logger.debug("开始滚动页面")

        for i in range(max_scrolls):
            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(0.5)

            # 检查是否已经到底部
            scroll_height = await self.page.evaluate("document.body.scrollHeight")
            current_scroll = await self.page.evaluate("window.scrollY")

            if scroll_height - current_scroll < 100:
                self.logger.debug(f"已滚动到页面底部（{i+1} 次）")
                break

    async def take_screenshot(self, filename: str = "screenshot.png") -> str:
        """
        截图

        Args:
            filename: 截图文件名

        Returns:
            截图路径
        """
        screenshot_dir = Path("data/screenshots")
        screenshot_dir.mkdir(parents=True, exist_ok=True)

        filepath = screenshot_dir / filename
        await self.page.screenshot(path=str(filepath), full_page=True)

        self.logger.debug(f"截图已保存: {filepath}")
        return str(filepath)

    async def handle_login_required(self) -> bool:
        """
        处理需要登录的情况

        Returns:
            是否已登录
        """
        # 等待用户手动登录
        if not self.headless:
            print("\n" + "="*60)
            print("需要登录")
            print("="*60)
            print("请在浏览器中完成登录，登录完成后按回车继续...")
            input()

            # 检查登录状态
            return await self.is_logged_in()
        else:
            self.logger.warning("无头模式下无法处理登录，请先手动登录")
            return False

    async def is_logged_in(self) -> bool:
        """
        检查是否已登录

        Returns:
            是否已登录
        """
        # 子类需要实现
        return True

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
            **kwargs: 其他参数

        Returns:
            职位列表
        """
        raise NotImplementedError("子类必须实现 search_jobs 方法")

    async def parse_job(self, job_url: str) -> Dict[str, Any]:
        """
        解析职位详情

        Args:
            job_url: 职位 URL

        Returns:
            职位详情
        """
        raise NotImplementedError("子类必须实现 parse_job 方法")

    async def apply_job(self, job_url: str, resume_path: str, **kwargs) -> bool:
        """
        申请职位

        Args:
            job_url: 职位 URL
            resume_path: 简历路径
            **kwargs: 其他参数

        Returns:
            是否申请成功
        """
        raise NotImplementedError("子类必须实现 apply_job 方法")

    def __repr__(self) -> str:
        return f"PlaywrightScraper(platform={self.platform_name}, headless={self.headless})"
