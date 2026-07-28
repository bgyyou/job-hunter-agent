"""M-v4-1 可观测性面板的纯聚合函数（被 pages/99_📊_Ops.py 调用，可单测）。

设计原则（来自 CLAUDE.md "第一性原理"）：
- DB 直连 vs factory 走 backend；backend 屏蔽 dialect 差异，但 SQLite 的 json_extract 与
  PG 的 details->>'key' 不一样，所以这里分两个分支：backend 类型嗅探 + 分发 SQL。
- 函数全部吃 backend 实例，不 import streamlit，方便脱离 UI 跑测试。
- 空数据 / 0 行 → 返回 shape 一致（rate=0.0, count=0, p95=0）；Streamlit 侧负责"暂无数据"
  文案提示。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


# 阈值常量（与 pages/99_📊_Ops.py 共用，避免两边漂移）
MOCK_FALLBACK_RED = 0.10     # ≥10% 红
MOCK_FALLBACK_YELLOW = 0.03  # 3-10% 黄；<3% 绿


def threshold_color(rate: float) -> str:
    """Mock fallback rate → "red" / "yellow" / "green"。

    Args:
        rate: 0.0-1.0 的比例；None 或负数按 0 处理。
    Returns:
        "red" | "yellow" | "green"
    """
    rate = max(0.0, float(rate or 0.0))
    if rate >= MOCK_FALLBACK_RED:
        return "red"
    if rate >= MOCK_FALLBACK_YELLOW:
        return "yellow"
    return "green"


# ---------------------------------------------------------------------------
# Backend 嗅探
# ---------------------------------------------------------------------------
def _is_sqlite(backend: Any) -> bool:
    """backend 是不是 SqliteBackend 实例？仅用于挑 JSON 提取函数。"""
    cls_name = type(backend).__name__
    if cls_name == "SqliteBackend":
        return True
    # 兜底：duck typing
    return hasattr(backend, "_get_conn") and hasattr(backend, "db_path")


def _is_postgres(backend: Any) -> bool:
    cls_name = type(backend).__name__
    return cls_name == "PostgresBackend"


def _json_extract_sql(col: str, key: str) -> Tuple[str, Tuple[Any, ...]]:
    """跨 dialect 提取 JSON 列里的字段。

    SQLite: json_extract(col, '$.key')。PG: (col->>'key')。
    返回 (sql_expr, params)：调用方负责把 sql_expr 嵌进 SELECT 子句。
    """
    # 简单实现：调用方传入 backend，决定走哪条分支。本函数是占位实现。
    raise NotImplementedError("use _json_extract_sqlite / _json_extract_pg directly")


def _json_extract_sqlite(col: str, key: str) -> str:
    """SQLite: json_extract(col, '$.key')。"""
    # 防止 key 含单引号：key 来自代码常量，可控；此处仍做最简转义。
    safe = key.replace("'", "''")
    return f"json_extract({col}, '$.{safe}')"


def _json_extract_pg(col: str, key: str) -> str:
    """PostgreSQL: (col->>'key')。"""
    safe = key.replace("'", "''")
    return f"({col}->>'{safe}')"


def _now_minus_days_sql(days: int, sqlite: bool) -> str:
    """跨 dialect 的"最近 N 天"时间表达式（字符串）。"""
    if sqlite:
        return f"datetime('now', '-{int(days)} days')"
    return f"NOW() - INTERVAL '{int(days)} days'"


def _percentile_sql(expr: str, percentile: float, sqlite: bool) -> str:
    """跨 dialect 的百分位表达式（PG 原生 percentile_cont，SQLITE 无 → 返回 NULL 占位）。"""
    if sqlite:
        # SQLite 无 percentile_cont；面板展示 P95 时返回 None，由 UI 提示
        return "NULL"
    return f"percentile_cont({percentile}) WITHIN GROUP (ORDER BY {expr})"


# ---------------------------------------------------------------------------
# Panel 1: LLM judge mock fallback rate
# ---------------------------------------------------------------------------
def judge_mock_fallback_rate(backend: Any) -> Dict[str, Any]:
    """最近 7 天 judge 调用里走 mock fallback 的比例。

    数据源：llm_calls（status='cache_hit' 视作失败 judge；error_message 含
    'MOCK'/'FALLBACK' 也算 mock fallback；operation LIKE '%judge%'）。

    Returns:
        {
            "total_judge_calls": int,
            "mock_fallback_calls": int,
            "mock_fallback_rate": float (0.0-1.0),
            "by_day": [{"day": "2026-07-22", "total": int, "mock": int}, ...]  最近 7 天
        }
    """
    sqlite = _is_sqlite(backend)
    days_expr = _now_minus_days_sql(7, sqlite)

    if sqlite:
        conn = backend._get_conn()
        try:
            # 总 judge 调用：operation 含 'judge' 或 'batch_judge'（run_eval.judge_batch_per_query）
            total = conn.execute(
                f"""
                SELECT COUNT(*) FROM llm_calls
                WHERE operation LIKE '%judge%' AND created_at >= {days_expr}
                """,
            ).fetchone()[0]
            # mock fallback：error_message 含 'MOCK' 或 'FALLBACK_MOCK'
            mock = conn.execute(
                f"""
                SELECT COUNT(*) FROM llm_calls
                WHERE operation LIKE '%judge%'
                  AND created_at >= {days_expr}
                  AND (error_message LIKE '%MOCK%' OR error_message LIKE '%FALLBACK%')
                """,
            ).fetchone()[0]
            # 按天聚合
            day_rows = conn.execute(
                f"""
                SELECT date(created_at) AS d,
                       COUNT(*) AS total,
                       SUM(CASE WHEN error_message LIKE '%MOCK%' OR error_message LIKE '%FALLBACK%'
                                THEN 1 ELSE 0 END) AS mock
                FROM llm_calls
                WHERE operation LIKE '%judge%' AND created_at >= {days_expr}
                GROUP BY date(created_at)
                ORDER BY d
                """,
            ).fetchall()
        finally:
            conn.close()
    else:
        cur = backend._get_conn().cursor()
        try:
            cur.execute(
                f"""
                SELECT COUNT(*) FROM llm_calls
                WHERE operation LIKE '%judge%' AND created_at >= {days_expr}
                """,
            )
            total = cur.fetchone()[0]
            cur.execute(
                f"""
                SELECT COUNT(*) FROM llm_calls
                WHERE operation LIKE '%judge%'
                  AND created_at >= {days_expr}
                  AND (error_message LIKE '%MOCK%' OR error_message LIKE '%FALLBACK%')
                """,
            )
            mock = cur.fetchone()[0]
            cur.execute(
                f"""
                SELECT to_char(date_trunc('day', created_at), 'YYYY-MM-DD') AS d,
                       COUNT(*) AS total,
                       SUM(CASE WHEN error_message LIKE '%MOCK%' OR error_message LIKE '%FALLBACK%'
                                THEN 1 ELSE 0 END) AS mock
                FROM llm_calls
                WHERE operation LIKE '%judge%' AND created_at >= {days_expr}
                GROUP BY date_trunc('day', created_at)
                ORDER BY d
                """,
            )
            day_rows = cur.fetchall()
        finally:
            cur.close()

    rate = (mock / total) if total else 0.0
    by_day = [{"day": r[0], "total": int(r[1]), "mock": int(r[2] or 0)} for r in (day_rows or [])]
    return {
        "total_judge_calls": int(total),
        "mock_fallback_calls": int(mock),
        "mock_fallback_rate": rate,
        "by_day": by_day,
    }


# ---------------------------------------------------------------------------
# Panel 2: Retrieval 耗时（avg / p95 / count）
# ---------------------------------------------------------------------------
def retrieval_latency(backend: Any) -> Dict[str, Any]:
    """最近 7 天 retrieval 操作的延迟统计。

    数据源：quality_checks（check_type='retrieval'，details 里有 latency_ms）。
    兼容 check_type='llm_call'（老代码曾混用）+ details.latency_ms 为 NULL 时跳过。

    Returns:
        {
            "count": int,
            "avg_ms": float,
            "p95_ms": Optional[float],  # SQLite 永远 None
            "by_phase": [{"phase": "rerank_on" / "rerank_off", "count": int, "avg_ms": float}, ...]
        }
    """
    sqlite = _is_sqlite(backend)
    days_expr = _now_minus_days_sql(7, sqlite)
    latency_expr = (_json_extract_sqlite("details", "latency_ms") if sqlite
                    else _json_extract_pg("details", "latency_ms"))

    if sqlite:
        conn = backend._get_conn()
        try:
            row = conn.execute(
                f"""
                SELECT COUNT(*) AS n,
                       AVG(CAST({latency_expr} AS REAL)) AS avg_ms
                FROM quality_checks
                WHERE check_type IN ('retrieval', 'llm_call')
                  AND {latency_expr} IS NOT NULL
                  AND checked_at >= {days_expr}
                """,
            ).fetchone()
            # SQLite 无 percentile_cont；p95 用 NULL 占位
            avg_ms = float(row[1] or 0.0)
            count = int(row[0])
            # phase 分组（如果有 details.rerank 标记）
            phase_rows = conn.execute(
                f"""
                SELECT COALESCE({_json_extract_sqlite('details', 'rerank')}, 'unknown') AS phase,
                       COUNT(*) AS n,
                       AVG(CAST({latency_expr} AS REAL)) AS avg_ms
                FROM quality_checks
                WHERE check_type IN ('retrieval', 'llm_call')
                  AND {latency_expr} IS NOT NULL
                  AND checked_at >= {days_expr}
                GROUP BY phase
                ORDER BY n DESC
                """,
            ).fetchall()
        finally:
            conn.close()
        p95_ms = None
    else:
        cur = backend._get_conn().cursor()
        try:
            cur.execute(
                f"""
                SELECT COUNT(*) AS n,
                       AVG(CAST({latency_expr} AS REAL)) AS avg_ms,
                       {_percentile_sql(latency_expr, 0.95, sqlite)} AS p95_ms
                FROM quality_checks
                WHERE check_type IN ('retrieval', 'llm_call')
                  AND {latency_expr} IS NOT NULL
                  AND checked_at >= {days_expr}
                """,
            )
            row = cur.fetchone()
            avg_ms = float(row[1] or 0.0)
            count = int(row[0])
            p95_ms = float(row[2]) if row[2] is not None else None
            cur.execute(
                f"""
                SELECT COALESCE({_json_extract_pg('details', 'rerank')}, 'unknown') AS phase,
                       COUNT(*) AS n,
                       AVG(CAST({latency_expr} AS REAL)) AS avg_ms
                FROM quality_checks
                WHERE check_type IN ('retrieval', 'llm_call')
                  AND {latency_expr} IS NOT NULL
                  AND checked_at >= {days_expr}
                GROUP BY phase
                ORDER BY n DESC
                """,
            )
            phase_rows = cur.fetchall()
        finally:
            cur.close()

    by_phase = [
        {"phase": str(r[0]), "count": int(r[1]), "avg_ms": float(r[2] or 0.0)}
        for r in (phase_rows or [])
    ]
    return {
        "count": count,
        "avg_ms": avg_ms,
        "p95_ms": p95_ms,
        "by_phase": by_phase,
    }


# ---------------------------------------------------------------------------
# Panel 3: LLM 调用成功率
# ---------------------------------------------------------------------------
def llm_success_rate(backend: Any, days: int = 7) -> Dict[str, Any]:
    """最近 N 天 llm_calls 表里 status='success' 的占比。

    注意：status ∈ {success, error, cache_hit}；cache_hit 不算 success
    也不算 error，按"业务上算成功"归入 success 分母。

    Returns:
        {
            "total": int,
            "success": int,
            "error": int,
            "cache_hit": int,
            "success_rate": float,  # (success + cache_hit) / total
            "error_rate": float,
        }
    """
    sqlite = _is_sqlite(backend)
    days_expr = _now_minus_days_sql(days, sqlite)

    if sqlite:
        conn = backend._get_conn()
        try:
            row = conn.execute(
                f"""
                SELECT
                  COUNT(*) AS total,
                  SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS n_success,
                  SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS n_error,
                  SUM(CASE WHEN status = 'cache_hit' THEN 1 ELSE 0 END) AS n_cache
                FROM llm_calls
                WHERE created_at >= {days_expr}
                """,
            ).fetchone()
        finally:
            conn.close()
    else:
        cur = backend._get_conn().cursor()
        try:
            cur.execute(
                f"""
                SELECT
                  COUNT(*) AS total,
                  SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS n_success,
                  SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS n_error,
                  SUM(CASE WHEN status = 'cache_hit' THEN 1 ELSE 0 END) AS n_cache
                FROM llm_calls
                WHERE created_at >= {days_expr}
                """,
            )
            row = cur.fetchone()
        finally:
            cur.close()

    total = int(row[0] or 0)
    success = int(row[1] or 0)
    error = int(row[2] or 0)
    cache = int(row[3] or 0)
    return {
        "total": total,
        "success": success,
        "error": error,
        "cache_hit": cache,
        "success_rate": ((success + cache) / total) if total else 0.0,
        "error_rate": (error / total) if total else 0.0,
    }


# ---------------------------------------------------------------------------
# Panel 4: Top 失败 case
# ---------------------------------------------------------------------------
def top_failure_cases(backend: Any, days: int = 7, limit: int = 10) -> List[Dict[str, Any]]:
    """最近 N 天按 (operation, error_type) 分组统计失败次数，倒序。

    数据源：llm_calls（status='error'）。

    Returns:
        [{"operation": str, "error_type": str, "count": int}, ...]
    """
    sqlite = _is_sqlite(backend)
    days_expr = _now_minus_days_sql(days, sqlite)

    if sqlite:
        conn = backend._get_conn()
        try:
            rows = conn.execute(
                f"""
                SELECT operation,
                       COALESCE(error_type, 'unknown') AS error_type,
                       COUNT(*) AS n
                FROM llm_calls
                WHERE status = 'error' AND created_at >= {days_expr}
                GROUP BY operation, error_type
                ORDER BY n DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        finally:
            conn.close()
    else:
        cur = backend._get_conn().cursor()
        try:
            cur.execute(
                f"""
                SELECT operation,
                       COALESCE(error_type, 'unknown') AS error_type,
                       COUNT(*) AS n
                FROM llm_calls
                WHERE status = 'error' AND created_at >= {days_expr}
                GROUP BY operation, error_type
                ORDER BY n DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
        finally:
            cur.close()

    return [
        {"operation": r[0], "error_type": r[1], "count": int(r[2])}
        for r in (rows or [])
    ]
