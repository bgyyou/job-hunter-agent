"""
HumanSimulator - 人类行为模拟器

模拟人类行为，用于反爬：
- 随机延迟
- 模拟鼠标移动
- 模拟滚动
- 模拟阅读时间
- 模拟点击行为
"""

import random
import time
import asyncio
from typing import Tuple, Optional
from loguru import logger


class HumanSimulator:
    """
    人类行为模拟器

    通过模拟真实人类行为来避免被反爬系统识别
    """

    def __init__(self, min_delay: float = 1.0, max_delay: float = 3.0):
        """
        初始化模拟器

        Args:
            min_delay: 最小延迟（秒）
            max_delay: 最大延迟（秒）
        """
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.logger = logger.bind(component="human_simulator")

    async def simulate_think_time(self, min_seconds: Optional[float] = None) -> float:
        """
        模拟思考时间

        Args:
            min_seconds: 最小秒数，None 则使用配置值

        Returns:
            实际延迟时间
        """
        min_s = min_seconds or self.min_delay
        delay = random.uniform(min_s, self.max_delay)

        # 偶尔模拟更长时间的思考
        if random.random() < 0.1:
            delay *= 2

        await asyncio.sleep(delay)
        self.logger.debug(f"模拟思考时间: {delay:.2f}s")

        return delay

    async def simulate_scroll(self, scroll_count: int = 1) -> Tuple[float, float]:
        """
        模拟滚动页面

        Args:
            scroll_count: 滚动次数

        Returns:
            (总延迟时间, 滚动距离)
        """
        total_delay = 0
        total_distance = 0

        for i in range(scroll_count):
            # 随机滚动距离
            distance = random.randint(200, 800)
            total_distance += distance

            # 滚动速度
            scroll_time = random.uniform(0.5, 2.0)

            # 滚动后停留
            pause_time = random.uniform(0.3, 1.0)

            delay = scroll_time + pause_time
            total_delay += delay

            await asyncio.sleep(delay)

            self.logger.debug(f"滚动 {i+1}/{scroll_count}: 距离={distance}, 耗时={delay:.2f}s")

        return (total_delay, total_distance)

    async def simulate_reading(self, text_length: int) -> float:
        """
        模拟阅读时间

        Args:
            text_length: 文本长度

        Returns:
            阅读时间
        """
        # 人类阅读速度：约 300-500 字/分钟（中文），200-300 词/分钟（英文）
        reading_speed = random.uniform(5, 10)  # 字/秒

        # 基础阅读时间
        base_time = text_length / reading_speed

        # 添加随机变量
        reading_time = base_time * random.uniform(0.8, 1.2)

        # 最少 1 秒
        reading_time = max(1.0, reading_time)

        await asyncio.sleep(reading_time)

        self.logger.debug(f"模拟阅读 {text_length} 字，耗时 {reading_time:.2f}s")

        return reading_time

    async def simulate_mouse_move(
        self,
        start: Tuple[int, int],
        end: Tuple[int, int]
    ) -> float:
        """
        模拟鼠标移动（仅记录，实际浏览器自动化需要 Playwright/Selenium）

        Args:
            start: 起点 (x, y)
            end: 终点 (x, y)

        Returns:
            移动时间
        """
        # 计算距离
        distance = ((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5

        # 移动速度：像素/秒
        speed = random.uniform(500, 1500)

        move_time = distance / speed

        # 添加随机抖动
        move_time *= random.uniform(0.9, 1.1)

        # 最少 0.1 秒
        move_time = max(0.1, move_time)

        await asyncio.sleep(move_time)

        self.logger.debug(f"模拟鼠标移动: {start} -> {end}, 距离={distance:.0f}, 耗时={move_time:.2f}s")

        return move_time

    async def simulate_click(self) -> float:
        """
        模拟点击行为

        Returns:
            延迟时间
        """
        # 点击前短暂停顿
        pre_click = random.uniform(0.1, 0.3)

        # 点击后短暂停顿
        post_click = random.uniform(0.2, 0.5)

        delay = pre_click + post_click

        await asyncio.sleep(delay)

        self.logger.debug(f"模拟点击，耗时 {delay:.2f}s")

        return delay

    async def simulate_typing(self, text: str) -> float:
        """
        模拟打字行为

        Args:
            text: 要输入的文本

        Returns:
            打字时间
        """
        total_time = 0

        for char in text:
            # 每个字符的打字时间
            char_time = random.uniform(0.05, 0.2)

            # 偶尔停顿（模拟思考或打错字）
            if random.random() < 0.05:
                char_time += random.uniform(0.3, 0.8)

            total_time += char_time
            await asyncio.sleep(char_time)

        self.logger.debug(f"模拟打字 {len(text)} 个字符，耗时 {total_time:.2f}s")

        return total_time

    async def simulate_form_fill(self, fields: dict) -> float:
        """
        模拟填写表单

        Args:
            fields: 字段字典 {field_name: value}

        Returns:
            总时间
        """
        total_time = 0

        for field_name, value in fields.items():
            # 找到字段的时间
            find_time = random.uniform(0.3, 1.0)
            await asyncio.sleep(find_time)
            total_time += find_time

            # 点击字段
            click_time = await self.simulate_click()
            total_time += click_time

            # 输入值
            if isinstance(value, str):
                type_time = await self.simulate_typing(value)
                total_time += type_time
            else:
                # 下拉选择等非输入字段
                select_time = random.uniform(0.2, 0.5)
                await asyncio.sleep(select_time)
                total_time += select_time

        self.logger.debug(f"模拟填写表单（{len(fields)} 个字段），耗时 {total_time:.2f}s")

        return total_time

    async def simulate_rest(self, min_seconds: float = 5.0) -> float:
        """
        模拟休息时间（模拟用户离开或切换页面）

        Args:
            min_seconds: 最小休息时间

        Returns:
            休息时间
        """
        rest_time = random.uniform(min_seconds, min_seconds * 3)

        await asyncio.sleep(rest_time)

        self.logger.debug(f"模拟休息，耗时 {rest_time:.2f}s")

        return rest_time

    def generate_random_headers(self) -> dict:
        """
        生成随机的浏览器 Headers

        Returns:
            Headers 字典
        """
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
        ]

        screen_sizes = [
            "1920x1080",
            "1366x768",
            "2560x1440",
            "1440x900",
        ]

        return {
            "User-Agent": random.choice(user_agents),
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"' if random.random() < 0.7 else '"macOS"',
        }

    def __repr__(self) -> str:
        return f"HumanSimulator(min_delay={self.min_delay}, max_delay={self.max_delay})"