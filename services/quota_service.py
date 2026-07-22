# -*- coding: utf-8 -*-
"""v4 T1.4：LLM 用量配额服务。

背景：v4 公网多用户 + 平台统一出 LLM key，无任何用量限制时一个重度用户
可以烧穿平台额度。本服务在 UI 动作前做两道闸门：

- 用户档：单用户当天 LLM 调用次数上限（LLM_USER_DAILY_CALL_LIMIT，默认 50）
- 全局档：全平台当天 LLM 调用次数熔断线（LLM_GLOBAL_DAILY_CALL_LIMIT，默认 2000）

统计口径：llm_calls 表当天记录，按 user_id 维度（013 迁移新增列）。
当天判断的 SQL 方言封装在 backend.get_llm_usage_today()
（SQLite ``date(created_at) = date('now')``，PG ``created_at::date = CURRENT_DATE``）。

建议接线方式（web_app.py，由主会话落地）::

    from database.factory import get_db
    from services.quota_service import QuotaService, QuotaExceededError

    quota = QuotaService(get_db())
    try:
        quota.check_quota(user_id)  # user_id 取当前登录用户，在触发 LLM 的 UI 动作前调用
    except QuotaExceededError as exc:
        st.warning(str(exc))
        st.stop()

注意：check_quota 只挡 UI 入口，不拦截已在进行中的调用；
llm_calls 由 tools/llm.py 的 _record_llm_call 事后落库，
因此并发下存在轻微的超限窗口，属于可接受的近似语义。
"""
from __future__ import annotations

from typing import Optional

from config.settings import Settings
from config.settings import settings as default_settings

# 面向用户的中文文案（两档必须可区分，测试按此断言）
USER_LIMIT_MESSAGE = "今日额度已用完，明天再来"
GLOBAL_LIMIT_MESSAGE = "平台今日总用量已达上限，请稍后再试"


class QuotaExceededError(Exception):
    """配额超限异常。

    Attributes:
        scope: ``"user"``（用户档）或 ``"global"``（全局熔断），
            便于上层按档位做差异化处理；str(exc) 即用户可读文案。
    """

    def __init__(self, message: str, scope: str = "user"):
        super().__init__(message)
        self.scope = scope


class QuotaService:
    """LLM 用量配额检查。db 为 BaseBackend 实例（database.factory.get_db()）。"""

    def __init__(self, db, settings: Optional[Settings] = None):
        self.db = db
        # 默认读全局 settings；测试可传入按 env 构造的 Settings()
        self.settings = settings or default_settings

    def get_usage_today(self, user_id: str) -> dict:
        """该用户当天用量：{"calls": int, "tokens": int}。"""
        return self.db.get_llm_usage_today(user_id)

    def check_quota(self, user_id: str) -> None:
        """超限抛 QuotaExceededError，否则静默返回。

        全局熔断优先于用户档：平台额度烧穿时所有用户看到的都应是全局文案。
        """
        global_usage = self.db.get_llm_usage_today()
        if global_usage["calls"] >= self.settings.llm_global_daily_call_limit:
            raise QuotaExceededError(GLOBAL_LIMIT_MESSAGE, scope="global")

        user_usage = self.db.get_llm_usage_today(user_id)
        if user_usage["calls"] >= self.settings.llm_user_daily_call_limit:
            raise QuotaExceededError(USER_LIMIT_MESSAGE, scope="user")
