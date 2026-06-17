# core/message_bus.py
from typing import Dict, List, Callable, Optional
import asyncio
from protocols.message import AgentMessage
from loguru import logger


class MessageBus:
    """消息总线 - Agent 之间通信的核心"""

    def __init__(self):
        self.handlers: Dict[str, List[Callable]] = {}
        self.message_log: List[AgentMessage] = []
        self.logger = logger.bind(component="message_bus")
        self._pending_requests: Dict[str, asyncio.Future] = {}

    def subscribe(self, agent_name: str, handler: Callable):
        """
        订阅消息

        Args:
            agent_name: Agent 名称
            handler: 消息处理函数
        """
        if agent_name not in self.handlers:
            self.handlers[agent_name] = []
        self.handlers[agent_name].append(handler)
        self.logger.debug(f"Agent {agent_name} 已订阅消息")

    async def publish(self, message: AgentMessage) -> List[any]:
        """
        发布消息

        Args:
            message: 消息对象

        Returns:
            处理结果列表
        """
        # 记录消息 - 可观测性
        self.message_log.append(message)
        self.logger.info(
            f"[消息] {message.from_agent} → {message.to_agent}: "
            f"{message.message_type.value}"
        )

        # 获取接收者处理器
        handlers = self.handlers.get(message.to_agent, [])
        if not handlers:
            self.logger.warning(f"无处理器接收消息: {message.to_agent}")
            return []

        # 执行处理器
        results = []
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    result = await handler(message)
                else:
                    result = handler(message)
                results.append(result)
            except Exception as e:
                self.logger.exception(f"处理器错误: {e}")
                results.append({"error": str(e)})

        return results

    async def request_response(self, message: AgentMessage,
                              timeout: float = 30.0) -> Optional[AgentMessage]:
        """
        发送请求并等待响应

        Args:
            message: 请求消息
            timeout: 超时时间（秒）

        Returns:
            响应消息，超时返回 None

        Raises:
            TimeoutError: 超时
        """
        message.requires_response = True

        # 创建等待 Future
        response_future = asyncio.Future()

        async def handle_response(resp_message: AgentMessage):
            if resp_message.correlation_id == message.message_id:
                if not response_future.done():
                    response_future.set_result(resp_message)

        # 临时订阅
        self.subscribe(message.from_agent, handle_response)

        # 发送请求
        await self.publish(message)

        # 等待响应
        try:
            response = await asyncio.wait_for(response_future, timeout=timeout)
            return response
        except asyncio.TimeoutError:
            raise TimeoutError(f"Agent 响应超时: {message.to_agent}")

    def get_message_log(self) -> List[AgentMessage]:
        """获取消息日志"""
        return self.message_log.copy()

    def clear_message_log(self):
        """清除消息日志"""
        self.message_log.clear()