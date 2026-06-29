# -*- coding: utf-8 -*-
"""v2.1 P1-16: 用户关键操作审计日志薄 helper。

设计原则：
1. **绝不影响业务**：内部 try/except 静默吞所有异常，埋点失败只 debug log
2. **薄封装**：只是 `db.insert_audit_log` 的参数收敛 + 异常隔离层
3. **action 命名约定**：`<domain>.<verb>` 例如 `user.login.success` / `resume.create`
   - domain: user / resume / jd / match / optimization
   - verb:  create / update / delete / login.success / login.failure

不记录 IP / UA：Streamlit 服务端拿不到客户端真实 IP（前端代理后才可见），
留待后续接 nginx/cloudflare 时再加 `client_ip` 字段。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from loguru import logger


def log_action(
    db: Any,
    *,
    user_id: str,
    action: str,
    target_table: Optional[str] = None,
    target_id: Optional[str] = None,
    status: str = "success",
    error_message: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """记录一条审计日志。失败时静默吞，绝不影响业务主流程。

    Args:
        db: backend instance（SqliteBackend / PostgresBackend）
        user_id: 操作发起者；未登录场景传 "default"
        action: 形如 ``'user.login.success'`` / ``'resume.create'``
        target_table: 受影响表名，如 ``'resumes'`` / ``'jds'``
        target_id: 受影响行 id
        status: ``'success'`` / ``'failure'``；默认 success
        error_message: status=failure 时填写
        details: 任意 JSON-serializable dict，用于补充上下文
    """
    try:
        db.insert_audit_log({
            "user_id": user_id,
            "action": action,
            "target_table": target_table,
            "target_id": target_id,
            "status": status,
            "error_message": error_message,
            "details": details,
        })
    except Exception as exc:
        logger.debug(f"audit_log record skipped: {exc}")
