# core/agent_harness.py
from typing import Dict, List, Any
from core.monitor import Monitor
from core.state_manager import StateManager
from loguru import logger


class AgentHarness:
    """Agent Harness - Agent 的运行环境"""

    def __init__(self):
        self.agents: Dict[str, "BaseAgent"] = {}
        self.monitor = Monitor()
        self.state_manager = StateManager()
        self.logger = logger.bind(component="harness")

    def register_agent(self, name: str, agent: "BaseAgent"):
        """
        注册 Agent

        Args:
            name: Agent 名称
            agent: Agent 实例
        """
        self.agents[name] = agent
        self.logger.info(f"Agent 已注册: {name}")

    def get_agent(self, name: str) -> "BaseAgent":
        """
        获取 Agent

        Args:
            name: Agent 名称

        Returns:
            Agent 实例

        Raises:
            ValueError: Agent 不存在
        """
        if name not in self.agents:
            raise ValueError(f"Agent 不存在: {name}")
        return self.agents[name]

    async def run_workflow(self, workflow: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        运行工作流

        Args:
            workflow: 工作流定义

        Returns:
            执行结果
        """
        self.logger.info(f"开始执行工作流，共 {len(workflow)} 个步骤")

        results = []

        for i, step in enumerate(workflow, 1):
            agent_name = step.get("agent")
            operation = step.get("operation", "execute")
            input_data = step.get("input", {})
            retry_on_error = step.get("retry_on_error", False)

            self.logger.info(f"步骤 {i}/{len(workflow)}: {agent_name}.{operation}")

            agent = self.get_agent(agent_name)

            try:
                # 执行 Agent
                result = await agent.safe_execute(input_data)

                results.append({
                    "step": i,
                    "agent": agent_name,
                    "operation": operation,
                    "result": result,
                    "status": "success" if result.get("status") == "success" else "error"
                })

            except Exception as e:
                self.logger.exception(f"步骤 {i} 执行失败: {e}")

                if not retry_on_error:
                    raise

                # 尝试恢复
                self.logger.info(f"尝试恢复 {agent_name}...")
                self.state_manager.load_state(agent_name)

        return {
            "status": "completed",
            "results": results,
            "metrics": self.monitor.get_report()
        }