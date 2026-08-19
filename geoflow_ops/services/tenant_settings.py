from __future__ import annotations

from django.db import connections

from geoflow_ops.process_workflow import (
    EVENT_DEFAULT_STAGE,
    EVENT_TYPE_CHOICES,
    STAGE_CHOICES,
    STATUS_CHOICES as EVENT_STATUS_CHOICES,
)


CONTRACT_STATUS_FALLBACK = (
    ("planned", "계약"),
    ("active", "진행"),
    ("pause", "중지"),
    ("complete", "준공"),
    ("cancel", "취소"),
)
CONTRACT_KIND_FALLBACK = (
    ("총액", "총액계약"),
    ("공동", "공동계약"),
    ("장기계속", "장기계속계약"),
    ("단가", "단가계약"),
    ("하도급", "하도급계약"),
)
EMPLOYMENT_TYPE_FALLBACK = (
    ("정규직", "정규직"),
    ("계약직", "계약직"),
    ("일용직", "일용직"),
    ("파견", "파견"),
    ("용역", "용역"),
    ("프리랜서", "프리랜서"),
    ("인턴", "인턴"),
)

# These event types carry core lifecycle semantics and must remain available
# even when an older tenant has a configured event-type tree that predates them.
SYSTEM_REQUIRED_EVENT_TYPES = {
    "event.type.closeout": (("closeout_complete", "준공완료"),),
}

CONTRACT_STATUS_ALIASES = {
    "planned": "planned",
    "계약전": "planned",
    "계약": "planned",
    "active": "active",
    "진행": "active",
    "진행중": "active",
    "pause": "pause",
    "paused": "pause",
    "중지": "pause",
    "보류": "pause",
    "complete": "complete",
    "completed": "complete",
    "완료": "complete",
    "준공": "complete",
    "cancel": "cancel",
    "canceled": "cancel",
    "cancelled": "cancel",
    "취소": "cancel",
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


def normalize_contract_status(value: object) -> str:
    text = str(value or "").strip()
    return CONTRACT_STATUS_ALIASES.get(text.lower(), CONTRACT_STATUS_ALIASES.get(text, text))


def _fallback_for(system_key: str):
    if system_key == "contract.status":
        return CONTRACT_STATUS_FALLBACK
    if system_key == "contract.kind":
        return CONTRACT_KIND_FALLBACK
    if system_key == "hr.employment_type":
        return EMPLOYMENT_TYPE_FALLBACK
    if system_key == "event.stage":
        return tuple((choice.code, choice.label) for choice in STAGE_CHOICES)
    if system_key == "event.status":
        return tuple((choice.code, choice.label) for choice in EVENT_STATUS_CHOICES)
    if system_key.startswith("event.type."):
        stage = system_key.rsplit(".", 1)[-1]
        labels = {choice.code: choice.label for choice in EVENT_TYPE_CHOICES}
        rows = [
            (event_type, labels.get(event_type, event_type))
            for event_type, default_stage in EVENT_DEFAULT_STAGE.items()
            if default_stage == stage
        ]
        rows.append(("etc", labels.get("etc", "기타")))
        return tuple(rows)
    return ()


def _configured_rows(alias: str, system_key: str):
    """Load the category identified by system_key.

    For event.type.<stage>, custom tenant stages can use a child category under
    the locked `event.type` root whose code exactly matches the stage code. This
    keeps custom hierarchy tenant-editable without requiring tenants to author
    internal `system_key` values themselves.
    """
    with connections[alias].cursor() as cur:
        if system_key.startswith("event.type."):
            stage = system_key[len("event.type."):]
            cur.execute(
                """
                SELECT child.code, child.name, child.active
                  FROM ops.settings_nodes category
                  JOIN ops.settings_nodes child ON child.parent_id = category.id
                 WHERE category.active = true
                   AND (
                        category.system_key = %s
                        OR (
                            category.system_key IS NULL
                            AND category.code = %s
                            AND category.parent_id = (
                                SELECT id FROM ops.settings_nodes
                                 WHERE system_key='event.type'
                                 LIMIT 1
                            )
                        )
                   )
                 ORDER BY child.ord, child.name, child.code
                """,
                [system_key, stage],
            )
        else:
            cur.execute(
                """
                SELECT child.code, child.name, child.active
                  FROM ops.settings_nodes category
                  JOIN ops.settings_nodes child ON child.parent_id = category.id
                 WHERE category.system_key = %s
                   AND category.active = true
                 ORDER BY child.ord, child.name, child.code
                """,
                [system_key],
            )
        return cur.fetchall()


def _merge_required_options(system_key: str, options):
    result = list(options)
    seen = {str(code or "") for code, _label in result}
    for code, label in SYSTEM_REQUIRED_EVENT_TYPES.get(system_key, ()):
        if code not in seen:
            result.append((code, label))
            seen.add(code)
    return result


def _canonicalize_contract_status_labels(options):
    labels = dict(CONTRACT_STATUS_FALLBACK)
    return [
        (code, labels.get(normalize_contract_status(code), label))
        for code, label in options
    ]


def settings_options(alias: str | None, system_key: str, *, include_inactive: bool = False):
    """Return stable machine code + tenant-editable label pairs."""

    fallback = list(_fallback_for(system_key))
    if not alias or not _table_exists(alias, "ops.settings_nodes"):
        result = _merge_required_options(system_key, fallback)
        return _canonicalize_contract_status_labels(result) if system_key == "contract.status" else result

    try:
        rows = _configured_rows(alias, system_key)
    except Exception:
        result = _merge_required_options(system_key, fallback)
        return _canonicalize_contract_status_labels(result) if system_key == "contract.status" else result
    if not rows:
        result = _merge_required_options(system_key, fallback)
        return _canonicalize_contract_status_labels(result) if system_key == "contract.status" else result
    configured = [
        (row[0] or "", row[1] or row[0] or "")
        for row in rows
        if include_inactive or bool(row[2])
    ]
    result = _merge_required_options(system_key, configured)
    return _canonicalize_contract_status_labels(result) if system_key == "contract.status" else result


def settings_codes(alias: str | None, system_key: str, *, include_inactive: bool = False) -> set[str]:
    return {code for code, _label in settings_options(alias, system_key, include_inactive=include_inactive)}


def event_workflow_options(alias: str | None):
    stages = settings_options(alias, "event.stage")
    statuses = settings_options(alias, "event.status")
    types_by_stage = {
        stage_code: settings_options(alias, f"event.type.{stage_code}")
        for stage_code, _label in stages
    }
    return {
        "stages": stages,
        "statuses": statuses,
        "types_by_stage": types_by_stage,
    }


def event_type_allowed(alias: str | None, stage: str, event_type: str) -> bool:
    stage = str(stage or "").strip()
    event_type = str(event_type or "").strip()
    if not stage or not event_type:
        return False
    return event_type in settings_codes(alias, f"event.type.{stage}")
