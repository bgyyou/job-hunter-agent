# examples/llm_usage.py
"""
火山引擎 API 使用示例
"""
import asyncio
from tools.llm import VolcanoClient, LLMMessage, LLMModel


async def main():
    # 方式一：使用 Agnes API
    coding_client = VolcanoClient(
        api_key="REDACTED_LEAKED_KEY_ROTATED_2026_06_17",
        api_url="https://apihub.agnes-ai.com/v1",
        model="agnes-2.0-flash",
        is_coding_api=True
    )

    # 方式二：使用 Chat API（其他模型）
    chat_client = VolcanoClient(
        api_key="REDACTED_LEAKED_KEY_ROTATED_2026_06_17",
        api_url="https://apihub.agnes-ai.com/v1",
        model="agnes-2.0-flash",
        is_coding_api=False
    )

    # 简单问答
    messages = [LLMMessage(role="user", content="你好，请简单介绍一下你自己")]
    response = await coding_client.analyze(messages)

    print(f"响应: {response.content}")
    print(f"使用 Token: {response.tokens_used}")
    print(f"模型: {response.model}")

    # 带系统 Prompt 的调用
    messages = [
        LLMMessage(role="user", content="帮我分析这段简历的优势")
    ]
    response = await coding_client.analyze(
        messages,
        system_prompt="你是一个专业的招聘顾问，擅长分析简历"
    )

    print(f"\n带系统 Prompt 的响应: {response.content}")

    # 流式调用
    print("\n流式响应:")
    async for chunk in coding_client.analyze_stream(messages):
        print(chunk.content, end="", flush=True)
    print()

    # 结构化输出
    output_schema = {
        "type": "object",
        "properties": {
            "skills": {"type": "array", "items": {"type": "string"}},
            "experience_years": {"type": "number"},
            "summary": {"type": "string"}
        }
    }

    messages = [LLMMessage(role="user", content="张三，3年后端开发经验，熟悉Python、Django")]
    result = await coding_client.analyze_with_structured_output(
        messages=messages,
        output_schema=output_schema
    )

    print(f"\n结构化输出: {result}")

    # 查看统计
    stats = coding_client.get_stats()
    print(f"\n统计信息: {stats}")


if __name__ == "__main__":
    asyncio.run(main())