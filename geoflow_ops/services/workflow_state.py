from __future__ import annotations

from datetime import timedelta

from django.db import connections
from django.utils import timezone
from django.utils.dateparse import parse_date

from geoflow_ops.process_workflow import (
    CONTRACT_LIFECYCLE_STAGE_PHASES,
    DEFAULT_HIGHLIGHT_DAYS,
    DEPRECATED_EVENT_TYPE_CODES,
    EVENT_TYPE_CHOICES,
    normalize_stage,
    transition_stage_for_event,
)


_DISPLAY_MAJOR_LABELS = {
    "preparation": "준비",
    "contract": "계약",
    "kickoff": "착수",
    "execution": "수행",
    "closeout": "준공",
    "complete": "완료",
}
_EVENT_TYPE_LABELS = {choice.code: choice.label for choice in EVENT_TYPE_CHOICES}

# Shared list-core compatibility tokens only. These are presentation/filter
# adapters; they are not persisted workflow state.
_LIST_FILTER_KEY_BY_MAJOR = {
    "preparation": "planned",
    "contract": "planned",
    "kickoff": "active",
    "execution": "active",
    "closeout": "pause",
    "complete": "complete",
}

_PHASE_RANK = {
    "preparation": 0,
    "contract": 10,
    "kickoff": 20,
    "execution": 30,
    "closeout": 40,
    "complete": 50,
}


def major_phase_for_stage(stage: str | None) -> tuple[str, str]:
    """Return the exact six-stage process code and label."""
    normalized = normalize_stage(stage) or "preparation"
    if normalized not in CONTRACT_LIFECYCLE_STAGE_PHASES:
        normalized = "execution"
    return normalized, _DISPLAY_MAJOR_LABELS[normalized]


def fallback_stage_for_contract_status(status: str | None) -> str:
    """Deprecated compatibility helper for old callers only.

    Runtime workflow is event-derived; Contract.status is not the lifecycle
    source of truth.
    """
    status = str(status or "").strip().lower()
    if status in {"planned", "계약전"}:
        return "preparation"
    if status in {"complete", "completed", "완료"}:
        return "complete"
    return "execution"


def _stage_summary(stage: str | None) -> dict:
    stage = normalize_stage(stage) or "preparation"
    major_code = CONTRACT_LIFECYCLE_STAGE_PHASES.get(stage, "preparation")
    phase_class = {
        "preparation": "bg-warning text-dark",
        "contract": "bg-primary",
        "kickoff": "bg-info text-dark",
        "execution": "bg-success",
        "closeout": "bg-info text-dark",
        "complete": "bg-secondary",
    }.get(major_code, "bg-light text-dark")
    major_event_label = {
        "preparation": "계약 전 준비",
        "contract": "계약 체결",
        "kickoff": "착수계 제출",
        "execution": "착수 승인",
        "closeout": "준공계 제출",
        "complete": "준공 승인",
    }.get(major_code, "-")
    return {
        "stage": stage,
        "stage_label": _DISPLAY_MAJOR_LABELS.get(major_code, major_code),
        "major_event_label": major_event_label,
        "major_code": major_code,
        "major_label": _DISPLAY_MAJOR_LABELS.get(major_code, major_code),
        "filter_key": _LIST_FILTER_KEY_BY_MAJOR.get(major_code, "active"),
        "phase_class": phase_class,
        "is_complete": major_code == "complete",
        "active_event_labels": [],
    }


def _event_highlight_active(occurred_at, payload) -> bool:
    display = dict((payload or {}).get("display") or {})
    if not bool(display.get("highlight_enabled", False)):
        return False
    today = timezone.localdate()
    occurred = occurred_at or today
    if occurred > today:
        return False
    if bool(display.get("until_closed", False)):
        return True
    end_at = parse_date(str(display.get("end_at") or ""))
    if end_at:
        return today <= end_at
    try:
        days = int(display.get("highlight_days") or DEFAULT_HIGHLIGHT_DAYS)
    except (TypeError, ValueError):
        days = DEFAULT_HIGHLIGHT_DAYS
    days = max(1, min(days, 3650))
    return today <= occurred + timedelta(days=days - 1)


def contract_workflow_summaries(alias: str, contract_rows) -> dict[str, dict]:
    """Derive event-derived Process Stage and current event-type badges.

    Stage advances only through reviewed transition events. Ordinary events such
    as 변경, 업무보고, 중지/재개 and 준공검사는 history only. The
    highest reached transition wins, so later non-transition events cannot move
    the lifecycle backwards. Active event emphasis is returned separately as the
    exact configured event type label for `[Process Stage] [이벤트 유형]`.
    """
    contracts = {str(row.id): row for row in contract_rows}
    if not contracts:
        return {}
    reached: dict[str, tuple[int, str]] = {}
    active_labels: dict[str, list[str]] = {contract_id: [] for contract_id in contracts}
    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT contract_id::text, stage, event_type, occurred_at, payload
              FROM ops.process_events
             WHERE contract_id = ANY(%s::uuid[])
               AND COALESCE(status, '') <> 'void'
             ORDER BY occurred_at NULLS LAST, created_at
            """,
            [list(contracts.keys())],
        )
        for contract_id, raw_stage, raw_event_type, occurred_at, payload in cur.fetchall():
            event_type = str(raw_event_type or "").strip()
            target_stage = transition_stage_for_event(event_type)
            if not target_stage and event_type in DEPRECATED_EVENT_TYPE_CODES:
                legacy_stage = normalize_stage(raw_stage)
                if legacy_stage in CONTRACT_LIFECYCLE_STAGE_PHASES:
                    target_stage = legacy_stage
            if target_stage in _PHASE_RANK:
                rank = _PHASE_RANK[target_stage]
                current = reached.get(contract_id)
                if current is None or rank > current[0]:
                    reached[contract_id] = (rank, target_stage)
            if _event_highlight_active(occurred_at, payload):
                label = _EVENT_TYPE_LABELS.get(event_type, event_type)
                if label and label not in active_labels.setdefault(contract_id, []):
                    active_labels[contract_id].append(label)
    result: dict[str, dict] = {}
    for contract_id in contracts:
        stage = reached.get(contract_id, (0, "preparation"))[1]
        summary = _stage_summary(stage)
        summary["active_event_labels"] = active_labels.get(contract_id, [])
        result[contract_id] = summary
    return result


def contract_workflow_summary(alias: str, contract) -> dict:
    return contract_workflow_summaries(alias, [contract]).get(
        str(contract.id),
        _stage_summary("preparation"),
    )
