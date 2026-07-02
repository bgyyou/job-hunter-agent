# -*- coding: utf-8 -*-
"""简历库服务：版本树管理、主简历切换、克隆。

v2.1 N10：随「我的简历」页面一起落地。

设计要点：
- 一份简历可被克隆为新版本（version + 1, parent_resume_id 指父）
- 每个用户一份「主简历」（is_primary = 1），求职/匹配流程默认用它
- 主简历切换是事务性的：新主设为 1 的同时，其他全置为 0
- 软删除保留，deleted_at IS NULL 才出现
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional


class ResumeLibraryError(ValueError):
    pass


def list_resumes_flat(db: Any, user_id: str) -> List[Dict[str, Any]]:
    """扁平列表：所有未删除简历，按主简历优先 + 更新时间倒序。"""
    return db.list_resumes(user_id)


def list_resume_versions(db: Any, user_id: str) -> List[Dict[str, Any]]:
    """返回版本树结构。

    Returns:
        [
          {
            "root_id": "...",  # 该版本线的「根」（最早的祖先）
            "root_label": "v1 · 2026-06-01",
            "versions": [
              {"id": "...", "version": 1, "label": "基线", "is_primary": 0,
               "name": "...", "updated_at": "...", "parent_resume_id": None},
              ...
            ],
          },
          ...
        ]
    """
    flat = db.list_resumes(user_id)
    by_id: Dict[str, Dict[str, Any]] = {r["id"]: r for r in flat}

    # 找每份简历的「根」（沿 parent_resume_id 一直向上）
    def find_root(rid: str, seen: Optional[set] = None) -> str:
        seen = seen or set()
        if rid in seen:
            return rid
        seen.add(rid)
        r = by_id.get(rid)
        if not r or not r.get("parent_resume_id"):
            return rid
        parent_id = r["parent_resume_id"]
        if parent_id not in by_id:
            return rid
        return find_root(parent_id, seen)

    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in flat:
        root_id = find_root(r["id"])
        groups[root_id].append(r)

    result: List[Dict[str, Any]] = []
    # 主简历所在组排第一，其余按更新时间倒序
    primary_root: Optional[str] = None
    rest: List[List[Dict[str, Any]]] = []
    for root_id, versions in groups.items():
        if any(v.get("is_primary") for v in versions):
            primary_root = root_id
        else:
            rest.append(versions)

    def versions_sorted(versions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return sorted(versions, key=lambda v: (v.get("version") or 1, v.get("updated_at") or ""))

    if primary_root:
        result.append({
            "root_id": primary_root,
            "root_label": "当前主简历线",
            "versions": versions_sorted(groups[primary_root]),
        })

    rest.sort(key=lambda vs: max(v.get("updated_at") or "" for v in vs), reverse=True)
    for versions in rest:
        first = min(versions, key=lambda v: v.get("version") or 1)
        result.append({
            "root_id": first["id"],
            "root_label": f"基线 v{first.get('version') or 1}",
            "versions": versions_sorted(versions),
        })

    return result


def set_primary_resume(db: Any, user_id: str, resume_id: str) -> None:
    """切换主简历。"""
    target = db.get_resume(resume_id)
    if not target or target.get("user_id") != user_id:
        raise ResumeLibraryError(f"resume {resume_id} 不属于 user {user_id}")
    db.set_primary_resume(user_id, resume_id)


def get_primary_resume(db: Any, user_id: str) -> Optional[Dict[str, Any]]:
    """返回当前主简历；没有则返回最新一份。"""
    flat = db.list_resumes(user_id)
    for r in flat:
        if r.get("is_primary"):
            return r
    return flat[0] if flat else None


def clone_resume(
    db: Any,
    source_resume_id: str,
    user_id: str,
    version_label: Optional[str] = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> str:
    """基于已有简历克隆一份新版本。

    Args:
        source_resume_id: 被克隆的简历 id
        user_id: 用户 id（校验用）
        version_label: 新版本标签（UI 展示用，如 "针对字节跳动 JD 优化"）
        overrides: 覆盖字段（如新名字、修改后的 summary）
    """
    src = db.get_resume(source_resume_id)
    if not src or src.get("user_id") != user_id:
        raise ResumeLibraryError(f"resume {source_resume_id} 不属于 user {user_id}")
    payload = {"version_label": version_label}
    if overrides:
        payload.update(overrides)
    return db.clone_resume_as_version(source_resume_id, payload)
