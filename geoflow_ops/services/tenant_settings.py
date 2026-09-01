from __future__ import annotations

from django.db import connections

from geoflow_ops.process_workflow import (
    DEPRECATED_EVENT_TYPE_CODES,
    DEPRECATED_STAGE_CODES,
    STAGE_CHOICES,
    STATUS_CHOICES as EVENT_STATUS_CHOICES,
)

FIELD_REF_ALIASES = {
    "hr.employment_type": "employee.employment_type",
    "hr.status": "employee.status",
    "hr.technical_grade": "employee.technical_grade",
    "hr.position_grade": "employee.position_grade",
    "hr.position_title": "employee.position_title",
}

CONTRACT_STATUS_ALIASES = {"planned": "planned", "계약전": "planned", "active": "active", "진행": "active", "진행중": "active", "pause": "pause", "paused": "pause", "중지": "pause", "보류": "pause", "complete": "complete", "completed": "complete", "완료": "complete", "cancel": "cancel", "canceled": "cancel", "cancelled": "cancel", "취소": "cancel"}


def _table_exists(alias: str | None, relation: str) -> bool:
    if not alias:
        return False
    try:
        with connections[alias].cursor() as cur:
            cur.execute("SELECT to_regclass(%s) IS NOT NULL", [relation])
            row = cur.fetchone()
        return bool(row and row[0])
    except Exception:
        return False


def normalize_contract_status(value: object) -> str:
    text = str(value or "").strip()
    return CONTRACT_STATUS_ALIASES.get(text.lower(), CONTRACT_STATUS_ALIASES.get(text, text))


def _configured_rows(alias: str, field_ref: str):
    with connections[alias].cursor() as cur:
        if field_ref.startswith("event.type."):
            group = field_ref[len("event.type."):]
            cur.execute(
                """
                 SELECT child.code, child.name, child.active
                  FROM ops.settings_nodes root
                  JOIN ops.settings_nodes event_group ON event_group.parent_id = root.id
                  JOIN ops.settings_nodes child ON child.parent_id = event_group.id
                 WHERE root.field_ref = 'event.type'
                   AND root.active = true AND event_group.active = true
                   AND event_group.code = %s
                 ORDER BY child.ord, child.name, child.code
                """,
                [group],
            )
        else:
            cur.execute(
                """
                SELECT child.code, child.name, child.active
                  FROM ops.settings_nodes category
                  JOIN ops.settings_nodes child ON child.parent_id = category.id
                 WHERE category.field_ref = %s
                   AND category.active = true
                 ORDER BY child.ord, child.name, child.code
                """,
                [field_ref],
            )
        return cur.fetchall()


def settings_options(alias: str | None, field_ref: str, *, include_inactive: bool = False):
    field_ref = FIELD_REF_ALIASES.get(field_ref, field_ref)
    if field_ref == "event.status":
        return [(choice.code, choice.label) for choice in EVENT_STATUS_CHOICES]
    if not alias or not _table_exists(alias, "ops.settings_nodes"):
        return []
    try:
        rows = _configured_rows(alias, field_ref)
    except Exception:
        return []
    return [(row[0] or "", row[1] or row[0] or "") for row in rows if include_inactive or bool(row[2])]


def settings_codes(alias: str | None, system_key: str, *, include_inactive: bool = False) -> set[str]:
    return {code for code, _label in settings_options(alias, system_key, include_inactive=include_inactive)}


def event_workflow_options(alias: str | None):
    process_stages = [(code, label) for code, label in settings_options(alias, "event.stage") if code not in DEPRECATED_STAGE_CODES]
    required_stage_codes = {choice.code for choice in STAGE_CHOICES}
    process_stages = [row for row in process_stages if row[0] in required_stage_codes]
    categories = list(process_stages)
    categories.append(("settlement", "정산"))
    statuses = settings_options(alias, "event.status")
    types_by_stage = {}
    for group_code, _label in categories:
        options = settings_options(alias, f"event.type.{group_code}")
        # Canonical transition events remain selectable; retired history codes do not.
        options = [(code, label) for code, label in options if code not in DEPRECATED_EVENT_TYPE_CODES]
        types_by_stage[group_code] = options
    return {"stages": categories, "process_stages": process_stages, "statuses": statuses, "types_by_stage": types_by_stage}


def event_type_allowed(alias: str | None, stage: str, event_type: str) -> bool:
    stage = str(stage or "").strip()
    event_type = str(event_type or "").strip()
    if not stage or not event_type:
        return False
    if stage == "settlement":
        return event_type in settings_codes(alias, "event.type.settlement")
    return event_type in settings_codes(alias, f"event.type.{stage}")
