# agents/base.py
"""
Agent 基类 - 真正的 Agent 实现

具备能力：
1. 记忆能力 - 上下文管理、短期/长期记忆
2. 工具调用 - 知道何时调用哪个工具
3. 错误恢复 - 重试、降级、换策略
4. 可解释性 - 链路追踪、reasoning
5. 成本意识 - Token 监控、缓存
6. 规划能力 - 任务分解
7. 反思能力 - 自我评估
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Callable, List, Tuple
from datetime import datetime
from pathlib import Path
import json
import asyncio
from functools import wraps

from loguru import logger

from core.context import ContextManager
from core.tracer import AgentTracer
from core.monitor import Monitor
from core.cache import Cache
from protocols.message import AgentMessage, MessageType


class Tool:
    """工具定义"""

    def __init__(self, name: str, description: str, func: Callable):
        self.name = name
        self.description = description
        self.func = func

    async def call(self, **kwargs) -> Any:
        """调用工具"""
        return await self.func(**kwargs)


class AgentPlan:
    """Agent 的执行计划"""

    def __init__(self, goal: str):
        self.goal = goal
        self.steps: List[Dict[str, Any]] = []
        self.current_step = 0
        self.created_at = datetime.now()

    def add_step(self, step_name: str, tool: str, params: Dict[str, Any],
                 description: str = "", depends_on: Optional[List[int]] = None):
        """添加步骤"""
        step = {
            "name": step_name,
            "tool": tool,
            "params": params,
            "description": description,
            "depends_on": depends_on or [],
            "status": "pending",
            "result": None,
            "error": None,
            "retries": 0
        }
        self.steps.append(step)

    def get_next_step(self) -> Optional[Dict[str, Any]]:
        """获取下一个可执行的步骤"""
        for i, step in enumerate(self.steps):
            if step["status"] == "pending":
                # 检查依赖是否完成
                if all(self.steps[d]["status"] == "completed" for d in step["depends_on"]):
                    self.current_step = i
                    return step
        return None

    def mark_step_completed(self, step_idx: int, result: Any):
        """标记步骤完成"""
        if 0 <= step_idx < len(self.steps):
            self.steps[step_idx]["status"] = "completed"
            self.steps[step_idx]["result"] = result

    def mark_step_failed(self, step_idx: int, error: str):
        """标记步骤失败"""
        if 0 <= step_idx < len(self.steps):
            self.steps[step_idx]["status"] = "failed"
            self.steps[step_idx]["error"] = error

    def get_failed_steps(self) -> List[Dict[str, Any]]:
        """获取失败的步骤"""
        return [s for s in self.steps if s["status"] == "failed"]


class BaseAgent(ABC):
    """所有 Agent 的基类 - 真正的 Agent 实现"""

    # 全局共享的组件
    _context_manager: Optional[ContextManager] = None
    _tracer: Optional[AgentTracer] = None
    _monitor: Optional[Monitor] = None
    _message_bus = None
    _session_id: Optional[str] = None

    def __init__(self, name: str):
        self.name = name
        self.state: Dict[str, Any] = {}
        self._reasoning: str = ""
        self.logger = logger.bind(agent=name)
        self._state_dir = Path("data/agent_states")
        self._state_dir.mkdir(parents=True, exist_ok=True)

        # 工具注册表
        self._tools: Dict[str, Tool] = {}
        self._register_default_tools()

        # 错误恢复配置
        self._max_retries = 3
        self._retry_delay = 1.0

        # 规划能力
        self._current_plan: Optional[AgentPlan] = None

        # 反思记忆
        self._reflection_memory: List[Dict[str, Any]] = []

    # ==================== 核心能力：记忆 ====================

    @classmethod
    def init_context(cls, user_id: str = "default"):
        """初始化上下文管理器"""
        if cls._context_manager is None:
            cls._context_manager = ContextManager()
            cls._session_id = cls._context_manager.create_session(user_id)

    def get_context(self, max_tokens: Optional[int] = None) -> str:
        """获取上下文 - 记忆能力"""
        if self._context_manager is None:
            return ""
        return self._context_manager.get_context(self._session_id, max_tokens)

    def add_to_context(self, role: str, content: str, metadata: Optional[Dict] = None):
        """添加到上下文"""
        if self._context_manager is None:
            return
        self._context_manager.add_message(self._session_id, role, content, metadata)

    def compress_context(self):
        """压缩上下文 - 成本意识"""
        if self._context_manager is None:
            return
        self._context_manager.compress_context(self._session_id)

    # ==================== 核心能力：可解释性 ====================

    def start_span(self, operation: str):
        """开始追踪 span"""
        if self._tracer is None:
            return
        return self._tracer.start_span(self.name, operation)

    def end_span(self, success: bool = True, error: Optional[str] = None):
        """结束追踪 span"""
        if self._tracer is None:
            return
        self._tracer.end_span(success, error)

    def get_trace_viz(self) -> str:
        """获取追踪可视化"""
        if self._tracer is None:
            return ""
        return self._tracer.visualize()

    # ==================== 核心能力：成本意识 ====================

    def record_llm_call(self, tokens: int):
        """记录 LLM 调用 - 成本意识"""
        if self._monitor is None:
            return
        self._monitor.record_llm_call(tokens)

    def get_cost_estimate(self) -> Dict[str, Any]:
        """获取成本估算"""
        if self._monitor is None:
            return {}
        return self._monitor.get_report()

    # ==================== 核心能力：工具调用 ====================

    def register_tool(self, name: str, description: str, func: Callable):
        """注册工具"""
        self._tools[name] = Tool(name, description, func)
        self.logger.debug(f"工具已注册: {name}")

    def _register_default_tools(self):
        """注册默认工具"""
        pass

    async def call_tool(self, tool_name: str, **kwargs) -> Any:
        """调用工具 - 错误恢复"""
        if tool_name not in self._tools:
            raise ValueError(f"工具不存在: {tool_name}")

        tool = self._tools[tool_name]
        span = self.start_span(f"tool:{tool_name}")

        for attempt in range(self._max_retries):
            try:
                result = await tool.call(**kwargs)
                if span:
                    self.end_span(True)
                return result
            except Exception as e:
                self.logger.warning(f"工具调用失败 (尝试 {attempt + 1}/{self._max_retries}): {e}")

                if attempt < self._max_retries - 1:
                    await asyncio.sleep(self._retry_delay * (2 ** attempt))
                else:
                    if span:
                        self.end_span(False, str(e))
                    raise

    # ==================== 核心能力：规划 ====================

    async def plan(self, goal: str, input_data: Dict[str, Any]) -> AgentPlan:
        """
        规划执行步骤 - 规划能力

        子类可以重写此方法，实现动态规划
        """
        plan = AgentPlan(goal)
        # 默认计划：直接执行
        plan.add_step("execute", "execute", input_data, "执行核心逻辑")
        return plan

    async def execute_with_plan(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        基于计划的执行 - 规划能力 + 错误恢复

        Args:
            input_data: 输入数据

        Returns:
            执行结果
        """
        # 1. 规划
        goal = self._get_goal(input_data)
        self._current_plan = await self.plan(goal, input_data)

        self.logger.info(f"制定计划，共 {len(self._current_plan.steps)} 个步骤")
        for step in self._current_plan.steps:
            self.logger.debug(f"  - {step['name']}: {step['description']}")

        # 2. 执行计划
        results = {}
        while True:
            step = self._current_plan.get_next_step()
            if not step:
                break

            self.logger.info(f"执行步骤: {step['name']}")

            try:
                # 反思：检查是否需要调整策略
                if await self._should_adjust_strategy(step, results):
                    step = await self._adjust_strategy(step, results)

                # 执行步骤
                if step["tool"] == "execute":
                    result = await self.execute(input_data)
                else:
                    result = await self.call_tool(step["tool"], **step["params"])

                # 反思：评估结果质量
                quality = await self._evaluate_step_result(step, result)
                self.logger.info(f"步骤完成，质量评分: {quality}")

                if quality < 0.6:
                    # 质量不够，尝试修正
                    self.logger.warning("结果质量偏低，尝试修正")
                    result = await self._correct_result(step, result, quality)

                self._current_plan.mark_step_completed(
                    self._current_plan.current_step,
                    result
                )
                results[step["name"]] = result

            except Exception as e:
                self.logger.error(f"步骤失败: {e}")

                # 尝试恢复
                recovery_result = await self._recover_from_failure(step, e, results)
                if recovery_result is not None:
                    results[step["name"]] = recovery_result
                else:
                    self._current_plan.mark_step_failed(
                        self._current_plan.current_step,
                        str(e)
                    )

        # 3. 反思整体执行
        await self._reflect_on_execution(results)

        return {
            "status": "success" if not self._current_plan.get_failed_steps() else "partial",
            "results": results,
            "plan_summary": self._get_plan_summary(),
            "reasoning": self.reasoning
        }

    def _get_goal(self, input_data: Dict[str, Any]) -> str:
        """获取目标"""
        return f"{self.name} 处理输入数据"

    async def _should_adjust_strategy(self, step: Dict, results: Dict) -> bool:
        """判断是否需要调整策略"""
        return False

    async def _adjust_strategy(self, step: Dict, results: Dict) -> Dict:
        """调整策略"""
        return step

    async def _evaluate_step_result(self, step: Dict, result: Any) -> float:
        """评估步骤结果质量 - 反思能力"""
        return 1.0

    async def _correct_result(self, step: Dict, result: Any, quality: float) -> Any:
        """修正结果 - 反思能力"""
        return result

    async def _recover_from_failure(self, step: Dict, error: Exception, results: Dict) -> Optional[Any]:
        """从失败中恢复 - 错误恢复"""
        return None

    async def _reflect_on_execution(self, results: Dict):
        """对执行过程进行反思 - 反思能力"""
        reflection = {
            "timestamp": datetime.now().isoformat(),
            "agent": self.name,
            "steps_completed": len(results),
            "total_steps": len(self._current_plan.steps) if self._current_plan else 0,
            "reasoning": self.reasoning
        }
        self._reflection_memory.append(reflection)

    def _get_plan_summary(self) -> str:
        """获取计划摘要"""
        if not self._current_plan:
            return ""

        completed = sum(1 for s in self._current_plan.steps if s["status"] == "completed")
        failed = len(self._current_plan.get_failed_steps())

        return f"计划执行: {completed} 完成, {failed} 失败, 共 {len(self._current_plan.steps)} 步骤"

    # ==================== 核心能力：抽象方法 ====================

    @abstractmethod
    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行 Agent 的核心逻辑

        Args:
            input_data: 输入数据

        Returns:
            输出结果，包含 status 和相关数据
        """
        pass

    # ==================== 工具方法 ====================

    def log_action(self, action: str, details: Optional[Dict[str, Any]] = None):
        """记录操作日志 - 可观测性"""
        log_entry = {
            "agent": self.name,
            "action": action,
            "details": details or {},
            "timestamp": datetime.now().isoformat()
        }
        self.logger.info(f"{action}", extra=log_entry)

    def validate_input(self, input_data: Dict[str, Any]) -> bool:
        """验证输入 - 安全性"""
        if not isinstance(input_data, dict):
            self.logger.error("输入必须是字典类型")
            return False
        return True

    def save_state(self):
        """保存状态 - 可靠性"""
        state_file = self._state_dir / f"{self.name}.json"
        try:
            # 转换 datetime 对象为字符串
            serializable_state = self._make_serializable(self.state)
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump(serializable_state, f, ensure_ascii=False, indent=2)
            self.logger.debug(f"状态已保存: {state_file}")
        except Exception as e:
            self.logger.error(f"保存状态失败: {e}")

    def _make_serializable(self, obj: Any) -> Any:
        """转换对象为 JSON 可序列化的格式"""
        if isinstance(obj, dict):
            return {k: self._make_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [self._make_serializable(item) for item in obj]
        elif isinstance(obj, datetime):
            return obj.isoformat()
        else:
            return obj

    def load_state(self):
        """加载状态 - 可靠性"""
        state_file = self._state_dir / f"{self.name}.json"
        if not state_file.exists():
            self.logger.debug("状态文件不存在，使用空状态")
            return

        try:
            with open(state_file, "r", encoding="utf-8") as f:
                self.state = json.load(f)
            self.logger.debug(f"状态已加载: {state_file}")
        except Exception as e:
            self.logger.error(f"加载状态失败: {e}")
            self.state = {}

    @property
    def reasoning(self) -> str:
        """获取决策理由 - 决策透明"""
        return self._reasoning

    def set_reasoning(self, reasoning: str):
        """设置决策理由"""
        self._reasoning = reasoning

    async def safe_execute(self, input_data: Dict[str, Any],
                          use_planning: bool = False) -> Dict[str, Any]:
        """
        安全执行，包含错误处理

        Args:
            input_data: 输入数据
            use_planning: 是否使用规划模式（默认 True）

        Returns:
            执行结果
        """
        span = self.start_span("safe_execute")

        try:
            # 验证输入
            if not self.validate_input(input_data):
                if span:
                    self.end_span(False, "输入验证失败")
                return {
                    "status": "error",
                    "error": "输入验证失败",
                    "agent": self.name
                }

            # 加载状态
            self.load_state()

            # 添加到上下文
            self.add_to_context(
                "user",
                f"输入: {json.dumps(input_data, ensure_ascii=False)[:500]}",
                {"timestamp": datetime.now().isoformat()}
            )

            # 执行
            if use_planning:
                result = await self.execute_with_plan(input_data)
            else:
                result = await self.execute(input_data)

            # 保存状态
            self.save_state()

            # 添加结果到上下文
            self.add_to_context(
                "assistant",
                f"结果: {result.get('status', 'unknown')}",
                {"timestamp": datetime.now().isoformat()}
            )

            if span:
                self.end_span(True)

            return result

        except Exception as e:
            self.logger.exception(f"执行失败: {e}")
            if span:
                self.end_span(False, str(e))

            return {
                "status": "error",
                "error": str(e),
                "agent": self.name,
                "trace": self.get_trace_viz()
            }

    # ==================== 消息通信 ====================

    async def send_message(self, to_agent: str, message_type: MessageType,
                           payload: Dict[str, Any]) -> Optional[AgentMessage]:
        """发送消息给其他 Agent"""
        if self._message_bus is None:
            return None

        message = AgentMessage(
            from_agent=self.name,
            to_agent=to_agent,
            message_type=message_type,
            payload=payload
        )

        return await self._message_bus.request_response(message)

    def subscribe_messages(self, handler: Callable):
        """订阅消息"""
        if self._message_bus is None:
            return
        self._message_bus.subscribe(self.name, handler)


# ==================== 全局初始化 ====================

def init_global_components(user_id: str = "default"):
    """初始化全局组件"""
    BaseAgent._context_manager = ContextManager()
    BaseAgent._session_id = BaseAgent._context_manager.create_session(user_id)
    BaseAgent._tracer = AgentTracer()
    BaseAgent._monitor = Monitor()

    from core.message_bus import MessageBus
    BaseAgent._message_bus = MessageBus()

    logger.info("全局组件初始化完成")