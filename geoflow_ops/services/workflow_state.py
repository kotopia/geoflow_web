from __future__ import annotations

from django.db import connections

from geoflow_ops.process_workflow import (
    CONTRACT_LIFECYCLE_STAGE_PHASES,
    DEPRECATED_EVENT_TYPE_CODES,
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

    Runtime lifecycle rendering is event-derived. Historic completed status rows
    were already converted to explicit completion events by migration 0026.
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
    }


def contract_workflow_summaries(alias: str, contract_rows) -> dict[str, dict]:
    """Derive 준비 -> 계약 -> 착수 -> 수행 -> 준공 -> 완료 from event history.

    New workflow state advances only when a reviewed transition event occurs:
    계약 체결 -> 계약, 착수계 -> 착수, 착수승인 -> 수행,
    준공계 -> 준공, 준공승인 -> 완료.

    Ordinary events such as 변경, 업무보고, 용역중지/재개 and 준공검사는
    timeline history only and never advance Process Stage. Stage never regresses;
    the highest reached transition wins.

    Reviewed legacy transition event codes remain recognized. For other known
    legacy system event codes only, their historical stored stage is used as a
    compatibility fallback so deployed history does not unexpectedly regress.
    Billing/settlement stages never advance the technical Process Stage.
    """

    contracts = {str(row.id): row for row in contract_rows}
    if not contracts:
        return {}

    reached: dict[str, tuple[int, str]] = {}

    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT contract_id::text, stage, event_type
              FROM ops.process_events
             WHERE contract_id = ANY(%s::uuid[])
               AND COALESCE(status, '') <> 'void'
            """,
            [list(contracts.keys())],
        )
        for contract_id, raw_stage, raw_event_type in cur.fetchall():
            event_type = str(raw_event_type or "").strip()
            target_stage = transition_stage_for_event(event_type)

            if not target_stage and event_type in DEPRECATED_EVENT_TYPE_CODES:
                legacy_stage = normalize_stage(raw_stage)
                if legacy_stage in CONTRACT_LIFECYCLE_STAGE_PHASES:
                    target_stage = legacy_stage

            if target_stage not in _PHASE_RANK:
                # Finance, custom and ordinary non-transition events remain
                # timeline history only.
                continue

            rank = _PHASE_RANK[target_stage]
            current = reached.get(contract_id)
            if current is None or rank > current[0]:
                reached[contract_id] = (rank, target_stage)

    result: dict[str, dict] = {}
    for contract_id in contracts:
        stage = reached.get(contract_id, (0, "preparation"))[1]
        result[contract_id] = _stage_summary(stage)
    return result


def contract_workflow_summary(alias: str, contract) -> dict:
    return contract_workflow_summaries(alias, [contract]).get(
        str(contract.id),
        _stage_summary("preparation"),
    )
