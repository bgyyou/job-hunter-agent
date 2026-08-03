"""用户自由文本输入的长度闸门（P0-007）。

为什么需要服务端截断而不是只靠 `st.text_area(max_chars=...)`：
`max_chars` 是浏览器端约束，构造的 websocket 消息可以绕过；
所以每个"用户文本 → LLM"的提交路径都必须再过一次 `clamp_user_text`。

`max_chars` 仍然要加 —— 它负责在 UI 上即时反馈（Streamlit 会显示字符计数器），
避免用户粘完一大段才被告知截断。两层是互补的，不是重复。

阈值 20000 字符的由来：一份完整 JD / 简历中文文本通常 < 5000 字，
20000 留了 4 倍余量，同时按 ~1.5 token/汉字估算约 30k token，
在 max_context_tokens=100000 之内，不会撑爆单次 LLM 调用。
"""
from __future__ import annotations

MAX_USER_TEXT_CHARS = 20000


def clamp_user_text(text: str | None, limit: int = MAX_USER_TEXT_CHARS) -> tuple[str, bool]:
    """把用户粘贴的自由文本截断到 limit 字符。

    Args:
        text: 用户输入，允许 None
        limit: 上限字符数，默认 MAX_USER_TEXT_CHARS

    Returns:
        (截断后的文本, 是否发生了截断)
    """
    if not text:
        return "", False
    if len(text) <= limit:
        return text, False
    return text[:limit], True
