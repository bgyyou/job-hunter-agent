# agents/registry.py
from typing import Dict, Type, Optional
from agents.base import BaseAgent


class AgentRegistry:
    """Agent 注册表 - 扩展性"""

    _agents: Dict[str, Type[BaseAgent]] = {}

    @classmethod
    def register(cls, name: str, agent_class: Type[BaseAgent]):
        """
        注册 Agent

        Args:
            name: Agent 名称
            agent_class: Agent 类
        """
        if not issubclass(agent_class, BaseAgent):
            raise ValueError(f"{agent_class} 必须继承自 BaseAgent")

        cls._agents[name] = agent_class

    @classmethod
    def get(cls, name: str) -> Type[BaseAgent]:
        """
        获取 Agent 类

        Args:
            name: Agent 名称

        Returns:
            Agent 类

        Raises:
            ValueError: Agent 不存在
        """
        if name not in cls._agents:
            raise ValueError(f"Agent 不存在: {name}")
        return cls._agents[name]

    @classmethod
    def list_agents(cls) -> list:
        """列出所有已注册的 Agent"""
        return list(cls._agents.keys())

    @classmethod
    def create_instance(cls, name: str, *args, **kwargs) -> BaseAgent:
        """
        创建 Agent 实例

        Args:
            name: Agent 名称
            *args: 位置参数
            **kwargs: 关键字参数

        Returns:
            Agent 实例
        """
        agent_class = cls.get(name)
        return agent_class(*args, **kwargs)

    @classmethod
    def is_registered(cls, name: str) -> bool:
        """检查 Agent 是否已注册"""
        return name in cls._agents