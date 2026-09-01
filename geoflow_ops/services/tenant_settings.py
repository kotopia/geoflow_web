from __future__ import annotations

from django.db import connections

from geoflow_ops.process_workflow import CONTRACT_COMPLETION_EVENT_TYPE


LEGACY_FIELD_REFS = {
    "contract.kind": "contract.kind",
    "hr.employment_type": "employee.employment_type",
    "hr.status": "employee.status",
    "hr.technical_grade": "employee.technical_grade",
    "hr.position_grade": "employee.position_grade",
    "hr.position_title": "employee.position_title",
    "event.stage": "event.stage",
}


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


def _field_ref(value: str) -> str:
    return LEGACY_FIELD_REFS.get(str(value or "").strip(), str(value or "").strip())


def settings_options(alias: str | None, field_ref: str, *, include_inactive: bool = False):
    """Return stable internal value + label pairs for a logical field reference.

    `code` remains a temporary storage bridge for existing text columns. It is
    not exposed for tenant editing and can be removed after UUID reference
    columns complete their staged production cutover.
    """
    field_ref = _field_ref(field_ref)
    if field_ref == "event.status":
        return [("draft", "작성중"), ("open", "진행중"), ("done", "완료"), ("void", "취소")]
    if not alias or not _table_exists(alias, "ops.settings_nodes"):
        return []
    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT child.code, child.name
              FROM ops.settings_nodes category
              JOIN ops.settings_nodes child ON child.parent_id = category.id
             WHERE category.field_ref = %s
               AND category.active = true
               AND (%s OR child.active = true)
             ORDER BY child.ord, child.name, child.id
            """,
            [field_ref, include_inactive],
        )
        return [(row[0] or "", row[1] or "") for row in cur.fetchall()]


def settings_codes(alias: str | None, field_ref: str, *, include_inactive: bool = False) -> set[str]:
    return {value for value, _label in settings_options(alias, field_ref, include_inactive=include_inactive)}


def _event_types(alias: str, stage_code: str, *, include_inactive: bool = False):
    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT event_type.code, event_type.name
              FROM ops.settings_nodes category
              JOIN ops.settings_nodes event_group ON event_group.parent_id = category.id
              JOIN ops.settings_nodes event_type ON event_type.parent_id = event_group.id
             WHERE category.field_ref = 'event.type'
               AND event_group.code IN (%s, 'settlement')
               AND category.active = true AND event_group.active = true
               AND (%s OR event_type.active = true)
             ORDER BY event_type.ord, event_type.name, event_type.id
            """,
            [stage_code, include_inactive],
        )
        return [(row[0] or "", row[1] or "") for row in cur.fetchall()]


def event_workflow_options(alias: str | None):
    stages = settings_options(alias, "event.stage")
    if not alias or not _table_exists(alias, "ops.settings_nodes"):
        return {"stages": [], "statuses": [], "types_by_stage": {}}
    types_by_stage = {stage: _event_types(alias, stage) for stage, _label in stages}
    types_by_stage["closeout"] = [
        option for option in types_by_stage.get("closeout", [])
        if option[0] != CONTRACT_COMPLETION_EVENT_TYPE
    ]
    return {
        "stages": stages,
        "statuses": [("draft", "작성중"), ("open", "진행중"), ("done", "완료"), ("void", "취소")],
        "types_by_stage": types_by_stage,
    }


def event_type_allowed(alias: str | None, stage: str, event_type: str) -> bool:
    if not alias or not stage or not event_type or not _table_exists(alias, "ops.settings_nodes"):
        return False
    return str(event_type).strip() in {value for value, _label in _event_types(alias, str(stage).strip())}
