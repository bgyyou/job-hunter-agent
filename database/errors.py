"""JobHunter 跨模块友好异常类型。

历史：R13b-prep（2026-08-04）落地 R9-P2 时新建。LLM 429、DB lock、库切换失败
三处故障都需要把"裸异常"转成"带 UI 文案 + 是否允许重试"的异常，让 streamlit
层用 st.error(message) + st.button("重试") 渲染，而不是抛 traceback。

用法：
    from database.errors import UserFacingError
    try:
        do_thing()
    except SomeRawError:
        raise UserFacingError("服务繁忙，请稍后重试", retry=True)
"""
from __future__ import annotations


class UserFacingError(Exception):
    """带 UI 文案的异常。streamlit 层据此渲染 st.error + 可选重试按钮。

    Attributes:
        message: 给用户看的中文文案（短，不超 30 字）。
        retry: True 时 UI 应额外渲染"重试"按钮。
    """

    def __init__(self, message: str, retry: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.retry = retry