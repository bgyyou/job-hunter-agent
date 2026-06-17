# tools/llm.py
"""
LLM 封装层 - 支持火山引擎（豆包等模型）
提供统一的 LLM 调用接口、Token 计数、Prompt 缓存和流式响应
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, AsyncGenerator, Any, Union
from enum import Enum
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from loguru import logger
from diskcache import Cache
import aiohttp


class LLMModel(str, Enum):
    """支持的 LLM 模型（火山引擎）"""
    # 豆包系列（用户根据实际情况填写）
    DOUBAO_PRO = "agnes-2.0-flash"  # 豆包 Pro
    DOUBAO_LITE = "agnes-2.0-flash"  # 豆包 Lite
    DOUBAO_TURBO = "agnes-2.0-flash"   # 豆包 Turbo

    # GLM 系列
    GLM_4_7 = "agnes-2.0-flash"

    # 火山引擎 Coding 系列
    ARK_CODE_LATEST = "agnes-2.0-flash"

    # 自定义模型（用户可以在配置中指定）
    CUSTOM = "custom"


@dataclass
class LLMMessage:
    """LLM 消息"""
    role: str  # system, user, assistant
    content: str
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class LLMResponse:
    """LLM 响应"""
    content: str
    model: str
    tokens_used: int
    finish_reason: str
    reasoning: str = ""
    sources: List[Dict[str, Any]] = None

    def __post_init__(self):
        if self.sources is None:
            self.sources = []


@dataclass
class StreamChunk:
    """流式响应块"""
    content: str
    is_complete: bool = False
    metadata: Optional[Dict[str, Any]] = None


class LLMClient(ABC):
    """
    LLM 客户端基类
    提供统一的 LLM 调用接口
    """

    def __init__(self, model: str, cache_dir: str = "data/llm_cache"):
        """
        初始化 LLM 客户端

        Args:
            model: LLM 模型名称
            cache_dir: 缓存目录
        """
        self.model = model
        self.cache = Cache(cache_dir)
        self.logger = logger.bind(component="llm")
        self._total_tokens = 0
        self._total_calls = 0
        self._call_history: List[Dict] = []

    @abstractmethod
    async def analyze(
        self,
        messages: List[LLMMessage],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        use_cache: bool = True
    ) -> LLMResponse:
        """
        分析消息（主方法）

        Args:
            messages: 消息列表
            max_tokens: 最大 Token 数
            temperature: 温度参数
            use_cache: 是否使用缓存

        Returns:
            LLM 响应
        """
        pass

    @abstractmethod
    async def analyze_stream(
        self,
        messages: List[LLMMessage],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        use_cache: bool = False
    ) -> AsyncGenerator[StreamChunk, None]:
        """
        流式分析消息

        Args:
            messages: 消息列表
            max_tokens: 最大 Token 数
            temperature: 温度参数
            use_cache: 是否使用缓存

        Yields:
            流式响应块
        """
        pass

    def estimate_tokens(self, text: str) -> int:
        """
        估算 Token 数（效率）

        Args:
            text: 文本

        Returns:
            估算的 Token 数
        """
        # 中文约 1.5 tokens/字，英文约 0.25 tokens/字
        chinese_chars = len([c for c in text if '一' <= c <= '鿿'])
        english_chars = len(text) - chinese_chars
        return int(chinese_chars * 1.5 + english_chars * 0.25)

    def count_tokens(self, messages: List[LLMMessage]) -> int:
        """
        计算 Token 数

        Args:
            messages: 消息列表

        Returns:
            总 Token 数
        """
        total = 0
        for msg in messages:
            total += self.estimate_tokens(msg.content)
            # 添加每个消息的开销
            total += 10
        return total

    def _get_cache_key(self, messages: List[LLMMessage], **kwargs) -> str:
        """生成缓存键"""
        data = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "kwargs": kwargs
        }
        json_str = json.dumps(data, sort_keys=True)
        return hashlib.md5(json_str.encode()).hexdigest()

    def _get_cache(self, cache_key: str) -> Optional[LLMResponse]:
        """获取缓存"""
        cached = self.cache.get(cache_key)
        if cached:
            self.logger.debug(f"缓存命中: {cache_key[:8]}...")
            return LLMResponse(**cached)
        return None

    def _set_cache(self, cache_key: str, response: LLMResponse, ttl: int = 3600):
        """设置缓存"""
        data = {
            "content": response.content,
            "model": response.model,
            "tokens_used": response.tokens_used,
            "finish_reason": response.finish_reason,
            "reasoning": response.reasoning,
            "sources": response.sources or []
        }
        self.cache.set(cache_key, data, expire=ttl)

    def record_call(self, tokens: int, metadata: Optional[Dict] = None):
        """记录调用"""
        self._total_tokens += tokens
        self._total_calls += 1
        self._call_history.append({
            "timestamp": time.time(),
            "model": self.model,
            "tokens": tokens,
            "metadata": metadata or {}
        })

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "total_calls": self._total_calls,
            "total_tokens": self._total_tokens,
            "avg_tokens_per_call": self._total_tokens / self._total_calls if self._total_calls > 0 else 0,
            "model": self.model
        }

    def reset_stats(self):
        """重置统计"""
        self._total_tokens = 0
        self._total_calls = 0
        self._call_history = []

    def estimate_cost(self, tokens: int, pricing: Optional[Dict[str, float]] = None) -> float:
        """
        估算成本

        Args:
            tokens: Token 数
            pricing: 自定义定价（元/千tokens），格式：{"input": 0.001, "output": 0.002}

        Returns:
            估算成本（人民币）
        """
        if not pricing:
            # 默认豆包定价示例（实际价格以火山引擎为准）
            pricing = {"input": 0.0008, "output": 0.002}

        # 假设 50% 输入，50% 输出
        input_tokens = tokens * 0.5
        output_tokens = tokens * 0.5

        input_cost = (input_tokens / 1000) * pricing["input"]
        output_cost = (output_tokens / 1000) * pricing["output"]

        return input_cost + output_cost


class VolcanoClient(LLMClient):
    """
    火山引擎客户端（支持豆包等模型）
    支持 OpenAI 兼容接口和 Anthropic 格式接口
    """

    def __init__(
        self,
        api_key: str,
        api_url: str,
        model: str = "agnes-2.0-flash",
        cache_dir: str = "data/llm_cache",
        pricing: Optional[Dict[str, float]] = None,
        is_coding_api: bool = False,
        use_anthropic_format: bool = False
    ):
        """
        初始化火山引擎客户端

        Args:
            api_key: API Key
            api_url: API 地址
                - Chat API: https://apihub.agnes-ai.com/v1
                - Coding API: https://apihub.agnes-ai.com/v1
            model: 模型名称（如：agnes-2.0-flash）
            cache_dir: 缓存目录
            pricing: 自定义定价（元/千tokens）
            is_coding_api: 是否使用 Coding API（默认 False，使用 Chat API）
            use_anthropic_format: 是否使用 Anthropic 格式（默认 False，设为 True 以使用 Claude Code 相同的方式）
        """
        super().__init__(model, cache_dir)
        self.api_key = api_key
        self.api_url = api_url
        self.pricing = pricing
        self.is_coding_api = is_coding_api
        self.use_anthropic_format = use_anthropic_format

        # 根据格式设置不同的 headers
        if use_anthropic_format:
            self.headers = {
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01"
            }
            # 确保 URL 正确 — 处理用户可能传入带 /v1 或不带的情况
            url = api_url
            if not url.endswith("/"):
                url = url + "/"
            if "/v1/messages" not in url and url.rstrip("/").endswith("/v1"):
                # 用户已传入 /v1，追加 messages
                self.api_url = url + "messages"
            elif "/v1/messages" not in url:
                self.api_url = url + "v1/messages"
            else:
                self.api_url = url
        else:
            self.headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }
            # v2.1 M2.5.4: 自动补全 OpenAI 兼容的 chat endpoint
            # 之前 self.api_url 直接用入参（如 https://apihub.agnes-ai.com/v1），POST 后返回
            # 404 "Invalid URL (POST /v1)" — 命中缓存的旧请求看不到，新 prompt 必失败
            url = api_url.rstrip("/")
            if url.endswith("/chat/completions"):
                self.api_url = url
            elif url.endswith("/v1"):
                self.api_url = url + "/chat/completions"
            else:
                self.api_url = url + "/v1/chat/completions"

    async def analyze(
        self,
        messages: List[LLMMessage],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        use_cache: bool = True,
        system_prompt: Optional[str] = None
    ) -> LLMResponse:
        """
        分析消息

        Args:
            messages: 消息列表
            max_tokens: 最大 Token 数
            temperature: 温度参数
            use_cache: 是否使用缓存
            system_prompt: 系统 Prompt

        Returns:
            LLM 响应
        """
        # 检查缓存
        if use_cache:
            cache_key = self._get_cache_key(
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
                system_prompt=system_prompt
            )
            cached = self._get_cache(cache_key)
            if cached:
                return cached

        try:
            # 调用 API
            if self.use_anthropic_format:
                response = await self._call_api_anthropic(
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system_prompt=system_prompt
                )

                # 构建 LLMResponse (Anthropic 格式)
                result = LLMResponse(
                    content=response["content"][0]["text"],
                    model=response.get("model", self.model),
                    tokens_used=response["usage"]["input_tokens"] + response["usage"]["output_tokens"],
                    finish_reason=response.get("stop_reason", "stop")
                )
            else:
                # 转换消息格式
                api_messages = self._convert_messages(messages, system_prompt)

                # 调用 API (OpenAI 格式)
                response = await self._call_api(
                    messages=api_messages,
                    max_tokens=max_tokens,
                    temperature=temperature
                )

                # 构建 LLMResponse
                result = LLMResponse(
                    content=response["choices"][0]["message"]["content"],
                    model=response.get("model", self.model),
                    tokens_used=response["usage"]["total_tokens"],
                    finish_reason=response["choices"][0]["finish_reason"]
                )

            # 记录调用
            self.record_call(result.tokens_used)

            # 设置缓存
            if use_cache:
                self._set_cache(cache_key, result)

            return result

        except Exception as e:
            self.logger.error(f"LLM 调用失败: {e}")
            raise

    async def analyze_stream(
        self,
        messages: List[LLMMessage],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        use_cache: bool = False,
        system_prompt: Optional[str] = None
    ) -> AsyncGenerator[StreamChunk, None]:
        """
        流式分析消息

        Args:
            messages: 消息列表
            max_tokens: 最大 Token 数
            temperature: 温度参数
            use_cache: 是否使用缓存
            system_prompt: 系统 Prompt

        Yields:
            流式响应块
        """
        # 转换消息格式
        api_messages = self._convert_messages(messages, system_prompt)

        total_content = ""
        tokens_used = 0

        try:
            async for chunk in self._call_api_stream(
                messages=api_messages,
                max_tokens=max_tokens,
                temperature=temperature
            ):
                content = chunk.get("content", "")
                if content:
                    total_content += content
                    tokens_used = self.estimate_tokens(content)

                    yield StreamChunk(
                        content=content,
                        is_complete=False,
                        metadata={"tokens_accumulated": tokens_used}
                    )

            # 记录调用
            self.record_call(tokens_used)

            yield StreamChunk(
                content="",
                is_complete=True,
                metadata={"total_tokens": tokens_used}
            )

        except Exception as e:
            self.logger.error(f"流式 LLM 调用失败: {e}")
            raise

    def _convert_messages(self, messages: List[LLMMessage], system_prompt: Optional[str] = None) -> List[Dict]:
        """
        转换消息格式

        Args:
            messages: LLMMessage 列表
            system_prompt: 系统 Prompt

        Returns:
            API 消息格式
        """
        api_messages = []

        # 添加系统消息
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})

        # 添加其他消息
        for msg in messages:
            # 跳过重复的系统消息
            if msg.role == "system" and system_prompt:
                continue
            api_messages.append({
                "role": msg.role,
                "content": msg.content
            })

        return api_messages

    async def _call_api_anthropic(
        self,
        messages: List[LLMMessage],
        max_tokens: int,
        temperature: float,
        system_prompt: Optional[str] = None
    ) -> Dict:
        """
        调用火山引擎 API (Anthropic 格式)

        Args:
            messages: 消息列表
            max_tokens: 最大 Token 数
            temperature: 温度参数
            system_prompt: 系统 Prompt

        Returns:
            API 响应
        """
        # Anthropic 格式: system 作为单独参数，messages 只有 user/assistant
        anthropic_messages = []
        for msg in messages:
            if msg.role == "system":
                if not system_prompt:
                    system_prompt = msg.content
            else:
                anthropic_messages.append({
                    "role": msg.role,
                    "content": msg.content
                })

        payload = {
            "model": self.model,
            "messages": anthropic_messages,
            "max_tokens": max_tokens,
            "temperature": temperature
        }

        if system_prompt:
            payload["system"] = system_prompt

        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.api_url,
                headers=self.headers,
                json=payload
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"API 调用失败 ({response.status}): {error_text}")

                return await response.json()

    async def _call_api(
        self,
        messages: List[Dict],
        max_tokens: int,
        temperature: float
    ) -> Dict:
        """
        调用火山引擎 API (OpenAI 格式)

        Args:
            messages: 消息列表
            max_tokens: 最大 Token 数
            temperature: 温度参数

        Returns:
            API 响应
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature
        }

        # Coding API 可能需要不同的 payload 格式
        if self.is_coding_api:
            # Coding API 可能只需要 messages 和 model
            payload = {
                "model": self.model,
                "messages": messages
            }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.api_url,
                headers=self.headers,
                json=payload
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"API 调用失败 ({response.status}): {error_text}")

                response_data = await response.json()

                # 兼容不同的响应格式
                if "choices" in response_data:
                    # OpenAI 格式
                    return response_data
                elif "data" in response_data and "content" in response_data["data"]:
                    # Coding API 格式
                    return {
                        "choices": [{
                            "message": {"content": response_data["data"]["content"]},
                            "finish_reason": "stop"
                        }],
                        "usage": {"total_tokens": response_data.get("usage", {}).get("total_tokens", 0)},
                        "model": response_data.get("model", self.model)
                    }
                else:
                    return response_data

    async def _call_api_stream(
        self,
        messages: List[Dict],
        max_tokens: int,
        temperature: float
    ) -> AsyncGenerator[Dict, None]:
        """
        调用火山引擎 API（流式）

        Args:
            messages: 消息列表
            max_tokens: 最大 Token 数
            temperature: 温度参数

        Yields:
            流式响应块
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.api_url,
                headers=self.headers,
                json=payload
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"API 调用失败 ({response.status}): {error_text}")

                async for line in response.content:
                    line = line.decode('utf-8').strip()
                    if not line or line == "data: [DONE]":
                        continue

                    if line.startswith("data: "):
                        line = line[6:]
                        try:
                            data = json.loads(line)
                            if "choices" in data and data["choices"]:
                                delta = data["choices"][0].get("delta", {})
                                if "content" in delta:
                                    yield delta
                        except json.JSONDecodeError:
                            continue

    async def analyze_with_structured_output(
        self,
        messages: List[LLMMessage],
        output_schema: Dict[str, Any],
        max_tokens: int = 4096,
        temperature: float = 0.7
    ) -> Dict[str, Any]:
        """
        分析消息并返回结构化输出

        Args:
            messages: 消息列表
            output_schema: 输出模式（JSON Schema）
            max_tokens: 最大 Token 数
            temperature: 温度参数

        Returns:
            结构化输出
        """
        # 添加结构化输出要求到消息中
        structured_messages = messages.copy()
        schema_instruction = (
            "\n\n请按照以下 JSON 格式返回结果：\n"
            f"{json.dumps(output_schema, ensure_ascii=False, indent=2)}\n"
            "只返回 JSON，不要有其他文字。"
        )

        # 修改最后一条消息
        if structured_messages:
            last_msg = structured_messages[-1]
            structured_messages[-1] = LLMMessage(
                role=last_msg.role,
                content=last_msg.content + schema_instruction
            )

        response = await self.analyze(structured_messages, max_tokens, temperature)

        # 解析 JSON 响应
        try:
            # 提取 JSON 部分
            content = response.content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            return json.loads(content)
        except json.JSONDecodeError as e:
            self.logger.error(f"解析 JSON 失败: {e}, 原始内容: {response.content[:200]}")
            raise ValueError(f"LLM 返回的不是有效的 JSON: {e}")