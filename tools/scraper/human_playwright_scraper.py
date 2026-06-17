"""
HumanPlaywrightScraper - 真正的类人行为爬虫

模拟真实人类行为：
- 贝塞尔曲线鼠标移动
- 自然的点击和悬停
- 随机的浏览节奏
- 完整的反反爬措施
"""

import random
import math
import asyncio
from typing import Tuple, Optional, List, Dict, Any
from pathlib import Path
from loguru import logger

from .playwright_scraper import PlaywrightScraper
from .human_simulator import HumanSimulator


class HumanPlaywrightScraper(PlaywrightScraper):
    """
    真正的类人行为爬虫

    使用 Playwright 实现最接近人类的浏览行为
    """

    def __init__(
        self,
        platform_name: str,
        headless: bool = False,
        user_data_dir: Optional[str] = None,
        browser_type: str = "msedge",
        human_speed: float = 1.0,
    ):
        """
        初始化类人爬虫

        Args:
            platform_name: 平台名称
            headless: 是否无头模式
            user_data_dir: 用户数据目录
            browser_type: 浏览器类型
            human_speed: 人类速度因子（1.0=正常，0.5=较慢，2.0=较快）
        """
        super().__init__(
            platform_name=platform_name,
            headless=headless,
            user_data_dir=user_data_dir,
            browser_type=browser_type,
        )

        self.human_speed = human_speed
        self.human_simulator = HumanSimulator(min_delay=0.5 * human_speed, max_delay=2.0 * human_speed)
        self.last_mouse_pos = (100, 100)

    async def start(self):
        """启动浏览器，增加反反爬增强"""
        await super().start()

        # 注入更强的反反爬脚本
        await self._inject_stealth_scripts()

        self.logger.info("类人行为爬虫启动成功")

    async def _inject_stealth_scripts(self):
        """注入反反爬脚本（参考 puppeteer-extra-plugin-stealth）"""

        stealth_scripts = [
            # 1. 隐藏 WebDriver
            """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            delete window.__webdriver_script_func;
            delete window.__webdriver_script_fn;
            delete window.__driver_evaluate;
            delete window.__webdriver_evaluate;
            """,

            # 2. 修复 Chrome 属性
            """
            window.chrome = { runtime: {} };
            window.chrome.app = { isInstalled: false };
            window.chrome.runtime = {
                onMessage: {},
                sendMessage: function() {}
            };
            """,

            # 3. 模拟真实的插件
            """
            Object.defineProperty(navigator, 'plugins', {
                get: () => [
                    { description: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', name: 'Chrome PDF Plugin' },
                    { description: 'Portable Document Format', filename: 'internal-pdf-viewer', name: 'Chrome PDF Viewer' }
                ]
            });
            """,

            # 4. 模拟语言
            """
            Object.defineProperty(navigator, 'languages', {
                get: () => ['zh-CN', 'zh', 'en-US', 'en']
            });
            """,

            # 5. 覆盖权限 API
            """
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );
            """,

            # 6. WebGL 指纹混淆
            """
            const getParameter = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(parameter) {
                if (parameter === 37445) return 'Google Inc.';  // UNMASKED_VENDOR_WEBGL
                if (parameter === 37446) return 'ANGLE (Intel, Intel(R) HD Graphics 530 Direct3D11 vs_5_0 ps_5_0, D3D11)';  // UNMASKED_RENDERER_WEBGL
                return getParameter.apply(this, arguments);
            };
            """,

            # 7. 修复 console
            """
            if (window.console) {
                const originalDebug = console.debug;
                console.debug = function(...args) {
                    if (args[0] && args[0].toString().includes('DEBUG')) return;
                    if (originalDebug) return originalDebug.apply(this, args);
                };
            }
            """,

            # 8. 修复 Permissions API
            """
            if (Notification.permission === 'denied') {
                Object.defineProperty(Notification, 'permission', { get: () => 'default' });
            }
            """,
        ]

        for script in stealth_scripts:
            try:
                await self.page.add_init_script(script)
            except Exception as e:
                self.logger.debug(f"注入脚本失败: {e}")

    async def human_navigate(self, url: str) -> bool:
        """
        类人方式导航到 URL

        Args:
            url: 目标 URL

        Returns:
            是否成功
        """
        self.logger.info(f"类人导航到: {url}")

        # 模拟人类输入 URL 的方式
        try:
            # 先随机移动一下鼠标
            await self._random_mouse_wiggle()
            await asyncio.sleep(0.2 * self.human_speed)

            # 访问页面
            await self.page.goto(url, wait_until="domcontentloaded", timeout=60000)

            # 等待页面稳定
            await asyncio.sleep(2.0 * self.human_speed)

            # 模拟人类滚动一下
            await self._human_scroll(start_only=True)

            # 再等待内容加载
            await asyncio.sleep(1.0 * self.human_speed)

            # 保存截图
            try:
                await self.take_screenshot(f"human_nav_{Path(url).name[:20]}.png")
            except:
                pass

            return True

        except Exception as e:
            self.logger.error(f"导航失败: {e}")
            return False

    async def human_click_selector(self, selector: str, index: int = 0) -> bool:
        """
        类人方式点击元素

        Args:
            selector: CSS 选择器
            index: 元素索引

        Returns:
            是否成功
        """
        try:
            elements = await self.page.query_selector_all(selector)
            if not elements:
                self.logger.debug(f"未找到元素: {selector}")
                return False

            if index >= len(elements):
                self.logger.debug(f"索引超出范围: {index} >= {len(elements)}")
                return False

            element = elements[index]
            await self.human_click_element(element)
            return True

        except Exception as e:
            self.logger.error(f"点击元素失败: {e}")
            return False

    async def human_click_element(self, element) -> bool:
        """
        类人方式点击单个元素

        Args:
            element: Playwright 元素句柄

        Returns:
            是否成功
        """
        try:
            # 获取元素位置
            box = await element.bounding_box()
            if not box:
                self.logger.debug("无法获取元素边界")
                return False

            # 计算点击位置（元素中心附近的随机位置）
            target_x = box['x'] + box['width'] / 2 + random.uniform(-box['width'] / 4, box['width'] / 4)
            target_y = box['y'] + box['height'] / 2 + random.uniform(-box['height'] / 4, box['height'] / 4)

            # 类人移动鼠标到目标
            await self.human_mouse_move(target_x, target_y)

            # 悬停一下
            await asyncio.sleep(random.uniform(0.3, 0.8) * self.human_speed)

            # 点击
            await self.page.mouse.click(target_x, target_y, delay=int(random.uniform(50, 150)))

            # 点击后停留
            await asyncio.sleep(random.uniform(0.5, 1.5) * self.human_speed)

            return True

        except Exception as e:
            self.logger.error(f"点击失败: {e}")
            return False

    async def human_mouse_move(self, x: float, y: float):
        """
        类人鼠标移动（贝塞尔曲线）

        Args:
            x: 目标 X
            y: 目标 Y
        """
        start_x, start_y = self.last_mouse_pos
        target_x, target_y = x, y

        # 计算路径
        points = await self._generate_bezier_path(start_x, start_y, target_x, target_y)

        # 移动鼠标
        for point_x, point_y in points:
            await self.page.mouse.move(point_x, point_y)
            await asyncio.sleep(0.005 * self.human_speed)  # 每步短暂暂停

        # 更新位置
        self.last_mouse_pos = (target_x, target_y)

    async def _generate_bezier_path(
        self,
        start_x: float,
        start_y: float,
        end_x: float,
        end_y: float,
        steps: Optional[int] = None
    ) -> List[Tuple[float, float]]:
        """
        生成贝塞尔曲线路径

        Args:
            start_x: 起点 X
            start_y: 起点 Y
            end_x: 终点 X
            end_y: 终点 Y
            steps: 步数

        Returns:
            路径点列表
        """
        # 计算距离
        distance = math.hypot(end_x - start_x, end_y - start_y)

        # 根据距离确定步数
        if not steps:
            steps = max(20, min(100, int(distance / 10)))

        # 生成控制点（偏离直线）
        control_x = start_x + (end_x - start_x) / 2 + random.uniform(-distance / 4, distance / 4)
        control_y = start_y + (end_y - start_y) / 2 + random.uniform(-distance / 6, distance / 6)

        # 生成路径
        path = []
        for i in range(steps + 1):
            t = i / steps

            # 二次贝塞尔曲线
            x = (1 - t) ** 2 * start_x + 2 * (1 - t) * t * control_x + t ** 2 * end_x
            y = (1 - t) ** 2 * start_y + 2 * (1 - t) * t * control_y + t ** 2 * end_y

            # 增加微小抖动
            if 0 < i < steps:
                x += random.uniform(-2, 2)
                y += random.uniform(-2, 2)

            path.append((x, y))

        return path

    async def _random_mouse_wiggle(self):
        """随机鼠标小幅度移动"""
        current_x, current_y = self.last_mouse_pos
        for _ in range(random.randint(2, 5)):
            new_x = current_x + random.uniform(-30, 30)
            new_y = current_y + random.uniform(-30, 30)
            await self.page.mouse.move(new_x, new_y)
            await asyncio.sleep(random.uniform(0.05, 0.15) * self.human_speed)

        # 回到起点附近
        await self.page.mouse.move(current_x + random.uniform(-5, 5), current_y + random.uniform(-5, 5))

    async def _human_scroll(self, start_only: bool = False):
        """
        类人方式滚动页面

        Args:
            start_only: 只在开头滚动一点
        """
        if start_only:
            # 只滚动一点
            scroll_amount = random.randint(50, 150)
            await self.page.evaluate(f"window.scrollBy(0, {scroll_amount})")
            await asyncio.sleep(0.5 * self.human_speed)
            await self.page.evaluate(f"window.scrollBy(0, -{scroll_amount // 2})")
            await asyncio.sleep(0.3 * self.human_speed)
            return

        # 完整滚动
        max_scrolls = random.randint(2, 5)

        for _ in range(max_scrolls):
            scroll_amount = random.randint(200, 600)
            await self.page.evaluate(f"window.scrollBy(0, {scroll_amount})")

            # 滚动后停顿（模拟阅读）
            pause_time = random.uniform(0.5, 2.0) * self.human_speed
            await asyncio.sleep(pause_time)

        # 最后回到顶部
        await self.page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(0.5 * self.human_speed)

    async def human_type(self, text: str, selector: Optional[str] = None) -> bool:
        """
        类人方式输入文字

        Args:
            text: 要输入的文本
            selector: 可选，输入框选择器

        Returns:
            是否成功
        """
        try:
            if selector:
                await self.human_click_selector(selector)
                await asyncio.sleep(0.5 * self.human_speed)

            # 使用人类模拟器的打字模式
            for char in text:
                await self.page.keyboard.press(char)
                char_delay = random.uniform(0.05, 0.2) * self.human_speed

                # 偶尔的长停顿（思考或打错字）
                if random.random() < 0.08:
                    char_delay += random.uniform(0.3, 0.8)

                await asyncio.sleep(char_delay)

            # 偶尔加个回车
            if random.random() < 0.1:
                await asyncio.sleep(0.2 * self.human_speed)
                await self.page.keyboard.press("Enter")

            return True

        except Exception as e:
            self.logger.error(f"打字失败: {e}")
            return False

    async def human_read_page(self, min_seconds: float = 3.0, max_seconds: float = 10.0):
        """
        模拟人类阅读页面

        Args:
            min_seconds: 最小秒数
            max_seconds: 最大秒数
        """
        read_time = random.uniform(min_seconds, max_seconds) * self.human_speed
        self.logger.info(f"模拟阅读页面: {read_time:.1f}秒")

        # 边读边滚动
        start_time = asyncio.get_event_loop().time()
        elapsed = 0

        while elapsed < read_time:
            # 随机滚动
            scroll_amount = random.randint(-200, 300)
            await self.page.evaluate(f"window.scrollBy(0, {scroll_amount})")

            # 随机停顿
            pause_time = random.uniform(0.5, 2.0) * self.human_speed
            await asyncio.sleep(pause_time)

            elapsed = asyncio.get_event_loop().time() - start_time

    async def human_search_and_scrape(
        self,
        keyword: str,
        max_jobs: int = 30
    ) -> List[Dict[str, Any]]:
        """
        完整的类人搜索和爬取流程（需要子类实现具体选择器）

        Args:
            keyword: 搜索关键词
            max_jobs: 最大职位数

        Returns:
            职位列表
        """
        raise NotImplementedError("子类需实现具体的搜索逻辑")

    def __repr__(self) -> str:
        return f"HumanPlaywrightScraper(platform={self.platform_name}, speed={self.human_speed}x)"
