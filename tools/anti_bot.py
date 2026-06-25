"""
反爬策略工具

提供反爬检测和应对策略
"""

import asyncio
import random
import time
from typing import Dict, List, Optional, Tuple
from fake_useragent import UserAgent
from loguru import logger


class AntiBotDetector:
    """
    反爬检测器

    检测是否被反爬系统识别
    """

    # 反爬检测关键词
    ANTI_BOT_KEYWORDS = [
        "访问异常",
        "请先登录",
        "验证码",
        "captcha",
        "verify",
        "access denied",
        "forbidden",
        "blocked",
        "频率限制",
        "频繁访问",
        "请求过多",
        "需要验证",
        "security check",
        "人机验证",
        "robot",
    ]

    # 反爬状态码
    ANTI_BOT_STATUS_CODES = [403, 429, 503]

    def __init__(self):
        """初始化检测器"""
        self.ua = UserAgent()
        self.logger = logger.bind(component="anti_bot_detector")

    def detect_text(self, text: str) -> Tuple[bool, str]:
        content = (text or "").lower()
        for keyword in self.ANTI_BOT_KEYWORDS:
            if keyword.lower() in content:
                return True, f"检测到关键词: {keyword}"
        return False, ""

    def detect(self, response: object) -> Tuple[bool, str]:
        """
        检测是否被反爬

        Args:
            response: HTTP 响应对象

        Returns:
            (是否被反爬, 原因)
        """
        # 检查状态码
        if hasattr(response, "status_code"):
            if response.status_code in self.ANTI_BOT_STATUS_CODES:
                return True, f"状态码: {response.status_code}"

        # 检查响应内容
        if hasattr(response, "text"):
            detected, reason = self.detect_text(response.text)
            if detected:
                return True, reason

        # 检查重定向
        if hasattr(response, "history") and response.history:
            # 多次重定向可能是反爬
            if len(response.history) > 2:
                return True, f"重定向次数过多: {len(response.history)}"

        return False, ""

    def get_severity(self, reason: str) -> str:
        """
        获取反爬严重程度

        Args:
            reason: 反爬原因

        Returns:
            严重程度（low/medium/high）
        """
        if "验证码" in reason or "captcha" in reason:
            return "high"
        elif "403" in reason or "forbidden" in reason:
            return "high"
        elif "频率" in reason or "429" in reason:
            return "medium"
        else:
            return "low"


class AntiBotResponse:
    """
    反爬应对策略

    根据反爬严重程度采取不同应对措施
    """

    def __init__(self, severity: str, reason: str):
        """
        初始化应对策略

        Args:
            severity: 严重程度
            reason: 反爬原因
        """
        self.severity = severity
        self.reason = reason
        self.logger = logger.bind(component="anti_bot_response")

    async def handle(self) -> Dict[str, any]:
        """
        处理反爬

        Returns:
            处理结果字典
        """
        if self.severity == "high":
            return await self._handle_high()
        elif self.severity == "medium":
            return await self._handle_medium()
        else:
            return await self._handle_low()

    async def _handle_high(self) -> Dict[str, any]:
        """
        处理高严重程度的反爬

        策略：
        - 长时间等待
        - 更换 IP（需要代理）
        - 需要人工介入
        """
        self.logger.warning(f"严重反爬: {self.reason}")

        # 长时间等待
        wait_time = random.uniform(300, 600)  # 5-10 分钟
        self.logger.info(f"等待 {wait_time / 60:.1f} 分钟...")
        await asyncio.sleep(wait_time)

        return {
            "action": "long_wait",
            "wait_time": wait_time,
            "needs_human": True,
        }

    async def _handle_medium(self) -> Dict[str, any]:
        """
        处理中等严重程度的反爬

        策略：
        - 中等时间等待
        - 更换 User-Agent
        """
        self.logger.warning(f"中等反爬: {self.reason}")

        # 中等时间等待
        wait_time = random.uniform(30, 120)  # 30秒-2分钟
        self.logger.info(f"等待 {wait_time:.1f} 秒...")
        await asyncio.sleep(wait_time)

        return {
            "action": "medium_wait",
            "wait_time": wait_time,
            "needs_human": False,
        }

    async def _handle_low(self) -> Dict[str, any]:
        """
        处理低严重程度的反爬

        策略：
        - 短暂等待
        """
        self.logger.info(f"轻微反爬: {self.reason}")

        # 短暂等待
        wait_time = random.uniform(10, 30)  # 10-30秒
        self.logger.info(f"等待 {wait_time:.1f} 秒...")
        await asyncio.sleep(wait_time)

        return {
            "action": "short_wait",
            "wait_time": wait_time,
            "needs_human": False,
        }


class UserAgentRotator:
    """
    User-Agent 轮换器

    定期更换 User-Agent
    """

    def __init__(self):
        """初始化轮换器"""
        self.ua = UserAgent()
        self.user_agents = []

    def get_random(self) -> str:
        """
        获取随机 User-Agent

        Returns:
            User-Agent 字符串
        """
        try:
            return self.ua.random
        except Exception:
            # 备用 User-Agent 列表
            fallback_uas = [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            ]
            return random.choice(fallback_uas)

    def get_all(self) -> List[str]:
        """
        获取所有 User-Agent

        Returns:
            User-Agent 列表
        """
        uas = []
        for _ in range(10):
            uas.append(self.get_random())
        return list(set(uas))


class RequestThrottler:
    """
    请求节流器

    控制请求速率，避免触发反爬
    """

    def __init__(
        self,
        requests_per_minute: int = 30,
        burst_size: int = 5
    ):
        """
        初始化节流器

        Args:
            requests_per_minute: 每分钟请求数
            burst_size: 突发请求数
        """
        self.requests_per_minute = requests_per_minute
        self.burst_size = burst_size
        self.requests = []
        self.logger = logger.bind(component="request_throttler")

    async def acquire(self):
        """
        获取请求许可

        如果超过速率限制，会阻塞等待
        """
        now = time.time()

        # 清理超过 1 分钟的记录
        self.requests = [t for t in self.requests if now - t < 60]

        # 检查突发限制
        recent_count = sum(1 for t in self.requests if now - t < 5)
        if recent_count >= self.burst_size:
            wait_time = 5.0 - (now - self.requests[-1]) if self.requests else 5.0
            self.logger.info(f"突发限制，等待 {wait_time:.1f} 秒...")
            await asyncio.sleep(wait_time)
            now = time.time()

        # 检查速率限制
        if len(self.requests) >= self.requests_per_minute:
            wait_time = 60.0 - (now - self.requests[0])
            self.logger.info(f"速率限制，等待 {wait_time:.1f} 秒...")
            await asyncio.sleep(wait_time)

        self.requests.append(now)

    def get_stats(self) -> Dict[str, any]:
        """
        获取统计信息

        Returns:
            统计字典
        """
        now = time.time()
        recent_requests = [t for t in self.requests if now - t < 60]

        return {
            "requests_last_minute": len(recent_requests),
            "requests_per_minute": self.requests_per_minute,
            "burst_size": self.burst_size,
        }


class ProxyRotator:
    """
    代理轮换器

    定期更换代理 IP
    """

    def __init__(self, proxies: Optional[List[str]] = None):
        """
        初始化代理轮换器

        Args:
            proxies: 代理列表
        """
        self.proxies = proxies or []
        self.current_index = 0
        self.logger = logger.bind(component="proxy_rotator")

    def get_current_proxy(self) -> Optional[Dict[str, str]]:
        """
        获取当前代理

        Returns:
            代理字典，如 {"http": "...", "https": "..."}
        """
        if not self.proxies:
            return None

        proxy = self.proxies[self.current_index]
        return {
            "http": proxy,
            "https": proxy,
        }

    def rotate(self):
        """轮换到下一个代理"""
        if not self.proxies:
            return

        self.current_index = (self.current_index + 1) % len(self.proxies)
        self.logger.info(f"已轮换到代理: {self.proxies[self.current_index]}")

    def add_proxy(self, proxy: str):
        """
        添加代理

        Args:
            proxy: 代理地址
        """
        self.proxies.append(proxy)
        self.logger.info(f"已添加代理: {proxy}")

    def remove_proxy(self, proxy: str):
        """
        移除代理

        Args:
            proxy: 代理地址
        """
        if proxy in self.proxies:
            self.proxies.remove(proxy)
            self.logger.info(f"已移除代理: {proxy}")


# 便利函数
async def check_and_handle_anti_bot(response: object) -> Dict[str, any]:
    """
    检查并处理反爬

    Args:
        response: HTTP 响应对象

    Returns:
        处理结果
    """
    detector = AntiBotDetector()

    is_blocked, reason = detector.detect(response)

    if not is_blocked:
        return {
            "is_blocked": False,
            "action": "continue",
        }

    # 被反爬，处理
    severity = detector.get_severity(reason)
    handler = AntiBotResponse(severity, reason)
    result = await handler.handle()

    result.update({
        "is_blocked": True,
        "reason": reason,
        "severity": severity,
    })

    return result


def generate_headers() -> Dict[str, str]:
    """
    生成反爬友好的 Headers

    Returns:
        Headers 字典
    """
    rotator = UserAgentRotator()

    return {
        "User-Agent": rotator.get_random(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }


# 模块导出
__all__ = [
    "AntiBotDetector",
    "AntiBotResponse",
    "UserAgentRotator",
    "RequestThrottler",
    "ProxyRotator",
    "check_and_handle_anti_bot",
    "generate_headers",
]


# 异步模块导入
import asyncio