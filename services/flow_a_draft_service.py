# -*- coding: utf-8 -*-
"""Flow A draft persistence + deterministic section validation.

Root fix principle: LLM can ask/extract, but it must not own workflow state.
This service keeps Flow A progress recoverable and lets local validators decide
whether a section is complete enough to advance.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence


RECOVERABLE_STATUSES = ("draft", "generating", "failed")


@dataclass(frozen=True)
class SectionValidation:
    section_key: str
    complete: bool
    missing_fields: List[str]


_REQUIRED_FIELDS: Dict[str, Sequence[tuple[str, str]]] = {
    "experience": (
        ("company", "公司"),
        ("title", "职位"),
        ("duration", "起止时间"),
        ("achievements", "至少 1 个成果"),
    ),
    "projects": (
        ("name", "项目名"),
        ("role", "你的角色"),
        ("tech_stack", "技术栈"),
        ("description", "做了什么"),
        ("achievements", "主要成果"),
    ),
}


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(_has_value(v) for v in value)
    if isinstance(value, dict):
        return any(_has_value(v) for v in value.values())
    return bool(value)


def _as_items(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict) and data:
        return [data]
    return []


def validate_section_completion(section_key: str, data: Any) -> SectionValidation:
    """Validate whether a Flow A section can advance without LLM judgment.

    Only sections collected by LLM chat/paste need strict validation here. Other
    Flow A sections are handled by deterministic forms in ``web_app.py``.
    """
    required = _REQUIRED_FIELDS.get(section_key)
    if not required:
        return SectionValidation(section_key=section_key, complete=True, missing_fields=[])

    items = _as_items(data)
    label_prefix = "工作经历" if section_key == "experience" else "项目"
    if not items:
        return SectionValidation(
            section_key=section_key,
            complete=False,
            missing_fields=[f"至少 1 段{label_prefix}"],
        )

    missing: List[str] = []
    for idx, item in enumerate(items, start=1):
        prefix = f"第 {idx} 段工作经历" if section_key == "experience" else f"第 {idx} 个项目"
        for field, label in required:
            if not _has_value(item.get(field)):
                missing.append(f"{prefix}：{label}")

    return SectionValidation(section_key=section_key, complete=not missing, missing_fields=missing)


def missing_fields_label(missing_fields: Sequence[str], limit: int = 6) -> str:
    if not missing_fields:
        return ""
    shown = list(missing_fields[:limit])
    suffix = "" if len(missing_fields) <= limit else f" 等 {len(missing_fields)} 项"
    return "、".join(shown) + suffix


class FlowADraftService:
    """Thin service over backend Flow A draft methods.

    The backend owns SQL dialect details; this class owns user/status defaults and
    the recoverable-draft policy used by Streamlit.
    """

    def __init__(self, db: Any, user_id: str = "default") -> None:
        self.db = db
        self.user_id = user_id

    def upsert_draft(self, data: Dict[str, Any]) -> str:
        payload = dict(data)
        payload.setdefault("user_id", self.user_id)
        payload.setdefault("status", "draft")
        payload.setdefault("section_data", {})
        payload.setdefault("section_messages", {})
        payload.setdefault("section_status", {})
        payload.setdefault("generation_state", {})
        return self.db.upsert_flow_a_draft(payload)

    def get_draft(self, draft_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not draft_id:
            return None
        return self.db.get_flow_a_draft(draft_id)

    def get_latest_recoverable_draft(self) -> Optional[Dict[str, Any]]:
        return self.db.get_latest_flow_a_draft(
            user_id=self.user_id,
            statuses=RECOVERABLE_STATUSES,
        )

    def abandon_draft(self, draft_id: str) -> None:
        self.db.abandon_flow_a_draft(draft_id)

    def save_runtime_state(
        self,
        draft_id: Optional[str],
        *,
        industry: Optional[str],
        function: Optional[str],
        position: Optional[str],
        current_step: str,
        current_section: Optional[str],
        section_data: Dict[str, Any],
        section_messages: Dict[str, Any],
        section_done: Sequence[str],
        section_skipped: Sequence[str],
        generation_state: Optional[Dict[str, Any]] = None,
        status: str = "draft",
        last_error: Optional[str] = None,
    ) -> str:
        section_status = {
            key: "done" for key in section_done
        }
        section_status.update({key: "skipped" for key in section_skipped})
        if current_section and current_section not in section_status:
            section_status[current_section] = "in_progress"

        return self.upsert_draft({
            "id": draft_id,
            "status": status,
            "industry": industry,
            "function": function,
            "position": position,
            "current_step": current_step,
            "current_section": current_section,
            "section_data": section_data or {},
            "section_messages": section_messages or {},
            "section_status": section_status,
            "generation_state": generation_state or {},
            "last_error": last_error,
        })
