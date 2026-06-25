# -*- coding: utf-8 -*-
"""JD库服务：统一使用 SQLite jds 表，不再依赖旧 JSON KnowledgeBase。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional


CRAWLED_SOURCES = {
    "crawler",
    "jobsdb_batch",
    "liepin_batch",
    "jd_crawler",
    "smart_collector",
    "51job_batch",
}

GARBAGE_KEYWORDS = {
    "验证码",
    "captcha",
    "verify",
    "verification",
    "请先登录",
    "登录 / 注册",
    "登录/注册",
    "人机验证",
    "安全验证",
    "需要验证",
    "访问异常",
    "频繁访问",
    "security check",
    "access denied",
    "blocked",
    "manual auth",
}


def _visible_conditions(user_id: str, search: Optional[str], source: Optional[str]) -> tuple[List[str], List[Any]]:
    conditions = ["deleted_at IS NULL", "(user_id = ? OR is_public = 1)"]
    params: List[Any] = [user_id]
    if source:
        conditions.append("source = ?")
        params.append(source)
    if search:
        like = f"%{search.strip()}%"
        conditions.append("(title LIKE ? OR company LIKE ? OR raw_text LIKE ? OR position_tag LIKE ?)")
        params.extend([like, like, like, like])
    return conditions, params


class JdLibraryError(ValueError):
    pass


def ensure_public_seed_jds(db: Any) -> int:
    conn = db._get_conn()
    try:
        placeholders = ",".join("?" for _ in CRAWLED_SOURCES)
        cursor = conn.execute(
            f"""UPDATE jds
                SET is_public = 1, updated_at = ?
                WHERE user_id = 'default'
                  AND source IN ({placeholders})
                  AND deleted_at IS NULL
                  AND is_public = 0""",
            [datetime.now().isoformat(), *sorted(CRAWLED_SOURCES)],
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def list_visible_jds(
    db: Any,
    user_id: str,
    *,
    search: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    conn = db._get_conn()
    try:
        conditions, params = _visible_conditions(user_id, search, source)
        query = "SELECT * FROM jds WHERE " + " AND ".join(conditions)
        query += " ORDER BY is_public ASC, crawled_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(query, params).fetchall()
        return db._deserialize_all(rows, ["parsed_sections", "tags"])
    finally:
        conn.close()


def count_visible_jds(
    db: Any,
    user_id: str,
    *,
    search: Optional[str] = None,
    source: Optional[str] = None,
) -> int:
    conn = db._get_conn()
    try:
        conditions, params = _visible_conditions(user_id, search, source)
        query = "SELECT COUNT(*) FROM jds WHERE " + " AND ".join(conditions)
        return int(conn.execute(query, params).fetchone()[0])
    finally:
        conn.close()


def get_visible_jd(db: Any, user_id: str, jd_id: str) -> Optional[Dict[str, Any]]:
    conn = db._get_conn()
    try:
        row = conn.execute(
            """SELECT * FROM jds
               WHERE id = ?
                 AND deleted_at IS NULL
                 AND (user_id = ? OR is_public = 1)""",
            (jd_id, user_id),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["parsed_sections"] = db._json_deserialize(result.get("parsed_sections"))
        result["tags"] = db._json_deserialize(result.get("tags"))
        return result
    finally:
        conn.close()


def list_sources(db: Any, user_id: str) -> List[str]:
    conn = db._get_conn()
    try:
        rows = conn.execute(
            """SELECT DISTINCT source FROM jds
               WHERE deleted_at IS NULL
                 AND (user_id = ? OR is_public = 1)
               ORDER BY source""",
            (user_id,),
        ).fetchall()
        return [r[0] for r in rows if r[0]]
    finally:
        conn.close()


def insert_user_jd(db: Any, user_id: str, jd_payload: Dict[str, Any]) -> str:
    payload = dict(jd_payload)
    payload["user_id"] = user_id
    payload["is_public"] = 0
    return db.insert_jd(payload)


def delete_user_jd(db: Any, user_id: str, jd_id: str) -> None:
    jd = get_visible_jd(db, user_id, jd_id)
    if not jd:
        raise JdLibraryError("JD 不存在")
    if jd.get("user_id") != user_id:
        raise JdLibraryError("公共 JD 不能删除")
    db.soft_delete_jd(jd_id)


def contains_anti_bot_text(text: str) -> bool:
    lowered = (text or "").lower()
    return any(keyword.lower() in lowered for keyword in GARBAGE_KEYWORDS)


def is_garbage_jd(row: Dict[str, Any]) -> bool:
    source = row.get("source") or ""
    if source not in CRAWLED_SOURCES:
        return False

    title = (row.get("title") or "").strip()
    company = (row.get("company") or "").strip()
    raw_text = (row.get("raw_text") or "").strip()
    combined = "\n".join([title, company, raw_text])
    if not contains_anti_bot_text(combined):
        return False

    weak_job_signal = (
        len(raw_text) < 300
        or not title
        or not company
        or title in {"登录", "登录 / 注册", "访问异常", "安全验证", "人机验证"}
        or not (row.get("position_tag") or row.get("job_id") or row.get("parsed_sections"))
    )
    return weak_job_signal


def cleanup_garbage_public_jds(db: Any, *, dry_run: bool = True) -> List[Dict[str, Any]]:
    conn = db._get_conn()
    try:
        placeholders = ",".join("?" for _ in CRAWLED_SOURCES)
        rows = conn.execute(
            f"""SELECT * FROM jds
                WHERE deleted_at IS NULL
                  AND (is_public = 1 OR user_id = 'default')
                  AND source IN ({placeholders})""",
            sorted(CRAWLED_SOURCES),
        ).fetchall()
        candidates = db._deserialize_all(rows, ["parsed_sections", "tags"])
    finally:
        conn.close()

    garbage = [row for row in candidates if is_garbage_jd(row)]
    if not dry_run:
        for row in garbage:
            db.soft_delete_jd(row["id"])
    return garbage
