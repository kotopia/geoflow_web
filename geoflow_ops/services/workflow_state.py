from __future__ import annotations

from django.db import connections

from geoflow_ops.process_workflow import (
    CONTRACT_COMPLETION_EVENT_TYPE,
    CONTRACT_LIFECYCLE_STAGE_PHASES,
)


_DISPLAY_MAJOR_LABELS = {
    "contract": "계약",
    "execution": "진행",
    "closeout": "준공",
    "complete": "완료",
}

# Shared list-core compatibility tokens only. These are UI filter adapters and
# are not Contract.status values or persisted lifecycle state.
_LIST_FILTER_KEY_BY_MAJOR = {
    "contract": "planned",
    "execution": "active",
    "closeout": "pause",
    "complete": "complete",
}

_PHASE_RANK = {
    "contract": 10,
    "execution": 20,
    "closeout": 30,
}


def major_phase_for_stage(stage: str | None) -> tuple[str, str]:
    """Preserve the established stage-group helper contract for old callers."""
    stage = str(stage or "").strip()
    if stage in {"pre_contract", "contract"}:
        return "contract", "계약(전)"
    if stage in {"kickoff", "execution", "inspection"}:
        return "execution", "수행(진행)"
    if stage in {"closeout", "billing"}:
        return "closeout", "준공"
    return "execution", "수행(진행)"


def fallback_stage_for_contract_status(status: str | None) -> str:
    """Deprecated compatibility helper for old callers only.

    Contract lifecycle rendering does not call this function. Runtime lifecycle is
    event-only after migration 0026 converts historic completed status rows into
    explicit closeout_complete events.
    """
    status = str(status or "").strip().lower()
    if status in {"planned", "계약전"}:
        return "pre_contract"
    if status in {"complete", "completed", "완료"}:
        return "closeout"
    return "execution"


def _stage_summary(stage: str | None, *, is_complete: bool = False) -> dict:
    stage = str(stage or "").strip() or "contract"
    major_code = CONTRACT_LIFECYCLE_STAGE_PHASES.get(stage, "contract")
    if is_complete:
        major_code = "complete"

    phase_class = {
        "contract": "bg-warning text-dark",
        "execution": "bg-primary",
        "closeout": "bg-info text-dark",
        "complete": "bg-secondary",
    }.get(major_code, "bg-light text-dark")

    major_event_label = {
        "contract": "계약 생성",
        "execution": "업무단계: 착수/수행/검사",
        "closeout": "업무단계: 준공",
        "complete": "완료",
    }.get(major_code, "-")

    return {
        "stage": stage,
        "stage_label": major_event_label,
        "major_event_label": major_event_label,
        "major_code": major_code,
        "major_label": _DISPLAY_MAJOR_LABELS.get(major_code, major_code),
        "filter_key": _LIST_FILTER_KEY_BY_MAJOR.get(major_code, "active"),
        "phase_class": phase_class,
        "is_complete": major_code == "complete",
    }


def contract_workflow_summaries(alias: str, contract_rows) -> dict[str, dict]:
    """Derive 계약 -> 진행 -> 준공 -> 완료 entirely from event history.

    Coarse phase movement is based on the selected event *stage*, not event type:
    - pre_contract / contract -> 계약
    - kickoff / execution / inspection -> 진행
    - closeout -> 준공
    - billing -> no technical phase change

    Phase never regresses because the highest reached non-void phase wins.
    Therefore stage=kickoff + event_type=etc still starts 진행, and any non-void
    stage=closeout event enters 준공.

    Final 완료 is explicit and event-only. Only a non-void closeout_complete event
    marks the contract complete. Migration 0026 converts historic completed
    Contract.status rows into those events and clears the migrated legacy value,
    so this runtime service never reads or writes Contract.status.
    """

    contracts = {str(row.id): row for row in contract_rows}
    if not contracts:
        return {}

    reached: dict[str, tuple[int, str]] = {}
    completed_contracts: set[str] = set()

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
            stage = str(raw_stage or "").strip()
            event_type = str(raw_event_type or "").strip()

            if event_type == CONTRACT_COMPLETION_EVENT_TYPE:
                completed_contracts.add(contract_id)

            phase = CONTRACT_LIFECYCLE_STAGE_PHASES.get(stage)
            if not phase:
                # billing and custom/unknown stages remain timeline history only.
                continue

            rank = _PHASE_RANK[phase]
            current = reached.get(contract_id)
            if current is None or rank > current[0]:
                reached[contract_id] = (rank, stage)

    result: dict[str, dict] = {}
    for contract_id in contracts:
        stage = reached.get(contract_id, (0, "contract"))[1]
        result[contract_id] = _stage_summary(
            stage,
            is_complete=contract_id in completed_contracts,
        )
    return result


def contract_workflow_summary(alias: str, contract) -> dict:
    return contract_workflow_summaries(alias, [contract]).get(
        str(contract.id),
        _stage_summary("contract"),
    )
