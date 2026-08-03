"""v3 M-v4-1: 共享文本清理工具。

- strip_thinking：剥 LLM 输出的 reasoning block。
  支持两种形式（d2dbfb7 引入，2026-07-26）：
    1. ```thinking...``` (labeled fenced code block，**只动 labeled 的，不动 ```json``` 之类的 code fence**)
    2. <think>...</think> (plain tags)

  使用方：
  - services.translation_service（先于业务 prompt 解析）
  - services.resume_rewriter（先于 _strip_code_fence）

  注意：Minimax-M3 默认 writing-mode 是关闭的（2026-07-27 官方文档确认），
  但我们调用的实例会输出 `` block；现象未完全归因，先在 parser 层兜住。
  后续若 Minimax 端定位清楚/可控关掉，可降级回标准 reasoning_content 通道。
"""
from __future__ import annotations

import re

# 只匹配 labeled thinking fence：```thinking 或 ```reasoning 等。
# 关键：**不**匹配 ```json、```python、```yaml 等 code fence — 那些是正经 payload。
_THINKING_FENCE_RE = re.compile(
    r"```(?:thinking|reasoning|reflection|chain_of_thought)\b[\s\S]*?```",
    re.IGNORECASE,
)

# 匹配 <think>...</think> / <reasoning>...</reasoning> 等 plain tag。
# 限定 tag 名避免误伤业务 XML。
_THINKING_TAG_RE = re.compile(
    r"<(?:think|reasoning|reflection|chain_of_thought)\b[^>]*>[\s\S]*?</(?:think|reasoning|reflection|chain_of_thought)\s*>",
    re.IGNORECASE,
)


def strip_thinking(content: str) -> str:
    """Strip reasoning blocks from LLM output.

    Args:
        content: LLM 原始输出文本

    Returns:
        去掉 reasoning block 后的内容；如果没找到 reasoning block，原样返回。
        空输入返回空字符串。
    """
    if not content:
        return content or ""
    content = _THINKING_FENCE_RE.sub("", content).strip()
    content = _THINKING_TAG_RE.sub("", content).strip()
    return content
