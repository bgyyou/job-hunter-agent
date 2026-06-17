"""
AdaptiveRateLimiter - 自适应频率限制器

根据响应情况自动调整请求频率：
- 成功率降低时增加延迟
- 成功率提高时减少延迟
- 支持暂停/恢复
"""

import asyncio
import time
from typing import Optional
from collections import deque
from loguru import logger


class AdaptiveRateLimiter:
    """
    自适应频率限制器

    根据请求的成功/失败情况动态调整请求间隔
    """

    def __init__(
        self,
        initial_delay: float = 2.0,
        min_delay: float = 1.0,
        max_delay: float = 60.0,
        window_size: int = 10,
        success_threshold: float = 0.8,
        failure_penalty: float = 1.5,
        success_reward: float = 0.9
    ):
        """
        初始化频率限制器

        Args:
            initial_delay: 初始延迟（秒）
            min_delay: 最小延迟（秒）
            max_delay: 最大延迟（秒）
            window_size: 统计窗口大小
            success_threshold: 成功率阈值，低于此值增加延迟
            failure_penalty: 失败时的延迟倍数
            success_reward: 成功时的延迟倍数
        """
        self.current_delay = initial_delay
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.window_size = window_size
        self.success_threshold = success_threshold
        self.failure_penalty = failure_penalty
        self.success_reward = success_reward

        # 历史记录（True=成功，False=失败）
        self.history = deque(maxlen=window_size)

        # 统计数据
        self.total_requests = 0
        self.success_count = 0
        self.failure_count = 0

        # 最后一次请求时间
        self.last_request_time: Optional[float] = None

        # 暂停状态
        self._paused = False
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # 默认不暂停

        self.logger = logger.bind(component="rate_limiter")

    def get_success_rate(self) -> float:
        """
        获取当前成功率

        Returns:
            成功率（0-1）
        """
        if len(self.history) == 0:
            return 1.0

        return sum(self.history) / len(self.history)

    def get_request_stats(self) -> dict:
        """
        获取请求统计

        Returns:
            统计字典
        """
        return {
            "total_requests": self.total_requests,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate": self.get_success_rate(),
            "current_delay": self.current_delay,
        }

    def _adjust_delay(self):
        """根据成功率调整延迟"""
        success_rate = self.get_success_rate()

        old_delay = self.current_delay

        if success_rate < self.success_threshold:
            # 成功率低，增加延迟
            self.current_delay = min(
                self.current_delay * self.failure_penalty,
                self.max_delay
            )
            self.logger.info(
                f"成功率低 ({success_rate:.1%})，延迟: {old_delay:.2f}s -> {self.current_delay:.2f}s"
            )
        elif success_rate > 0.95 and self.current_delay > self.min_delay:
            # 成功率高，减少延迟
            self.current_delay = max(
                self.current_delay * self.success_reward,
                self.min_delay
            )
            self.logger.debug(
                f"成功率高 ({success_rate:.1%})，延迟: {old_delay:.2f}s -> {self.current_delay:.2f}s"
            )

    def record_success(self):
        """记录成功请求"""
        self.history.append(True)
        self.total_requests += 1
        self.success_count += 1
        self._adjust_delay()

    def record_failure(self):
        """记录失败请求"""
        self.history.append(False)
        self.total_requests += 1
        self.failure_count += 1
        self._adjust_delay()

    async def wait(self):
        """
        等待，确保不超速

        如果处于暂停状态，会阻塞直到恢复
        """
        # 等待恢复（如果暂停）
        await self._pause_event.wait()

        # 计算需要等待的时间
        if self.last_request_time:
            elapsed = time.time() - self.last_request_time
            if elapsed < self.current_delay:
                wait_time = self.current_delay - elapsed
                await asyncio.sleep(wait_time)

        self.last_request_time = time.time()
        self.logger.debug(f"等待完成，下次延迟: {self.current_delay:.2f}s")

    async def pause(self, duration: Optional[float] = None):
        """
        暂停请求

        Args:
            duration: 暂停时长（秒），None 表示无限期暂停
        """
        self._paused = True
        self._pause_event.clear()
        self.logger.warning(f"已暂停请求{'，将持续 ' + str(duration) + ' 秒' if duration else ''}")

        if duration:
            await asyncio.sleep(duration)
            self.resume()

    def resume(self):
        """恢复请求"""
        if self._paused:
            self._paused = False
            self._pause_event.set()
            self.logger.info("已恢复请求")

    def is_paused(self) -> bool:
        """
        检查是否暂停

        Returns:
            是否暂停
        """
        return self._paused

    def reset(self):
        """重置状态"""
        self.current_delay = 2.0
        self.history.clear()
        self.total_requests = 0
        self.success_count = 0
        self.failure_count = 0
        self.last_request_time = None

        if self._paused:
            self.resume()

        self.logger.info("已重置频率限制器")

    def force_delay(self, delay: float):
        """
        强制设置延迟

        Args:
            delay: 延迟时间（秒）
        """
        self.current_delay = max(self.min_delay, min(self.max_delay, delay))
        self.logger.info(f"强制设置延迟: {self.current_delay:.2f}s")

    def increase_delay(self, factor: float = 1.5):
        """
        增加延迟

        Args:
            factor: 倍数
        """
        self.current_delay = min(
            self.current_delay * factor,
            self.max_delay
        )
        self.logger.info(f"增加延迟: {self.current_delay:.2f}s")

    def decrease_delay(self, factor: float = 0.9):
        """
        减少延迟

        Args:
            factor: 倍数
        """
        self.current_delay = max(
            self.current_delay * factor,
            self.min_delay
        )
        self.logger.info(f"减少延迟: {self.current_delay:.2f}s")

    async def cooldown(self, duration: float = 60.0):
        """
        冷却期，暂停所有请求

        Args:
            duration: 冷却时长（秒）
        """
        self.logger.warning(f"进入冷却期，将持续 {duration} 秒")
        await self.pause(duration)

    def __repr__(self) -> str:
        return (
            f"AdaptiveRateLimiter(delay={self.current_delay:.2f}s, "
            f"success_rate={self.get_success_rate():.1%})"
        )