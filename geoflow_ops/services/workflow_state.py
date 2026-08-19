from __future__ import annotations

from django.db import connections

from geoflow_ops.process_workflow import CONTRACT_LIFECYCLE_MILESTONES


_DISPLAY_MAJOR_LABELS = {
    "contract": "계약",
    "execution": "진행",
    "closeout": "준공",
}
# Shared list-core compatibility tokens. These are UI filter adapters only and
# are not Contract.status values or database lifecycle state.
_LIST_FILTER_KEY_BY_MAJOR = {
    "contract": "planned",
    "execution": "active",
    "closeout": "complete",
}
_MILESTONE_RANK = {
    "kickoff": 20,
    "completion_doc": 30,
    "closeout_complete": 40,
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
    """Legacy compatibility helper only; lifecycle display does not call this."""
    status = str(status or "").strip().lower()
    if status in {"planned", "계약전"}:
        return "pre_contract"
    if status in {"complete", "completed", "완료"}:
        return "closeout"
    return "execution"


def _stage_summary(
    stage: str | None,
    *,
    contract_status: str | None = None,
    is_complete: bool = False,
    milestone_label: str | None = None,
) -> dict:
    # Event-driven callers pass an explicit phase stage. The status fallback is
    # retained solely for old internal callers during deprecation.
    stage = str(stage or "").strip() or fallback_stage_for_contract_status(contract_status)
    major_code, legacy_major_label = major_phase_for_stage(stage)
    major_label = _DISPLAY_MAJOR_LABELS.get(major_code, legacy_major_label)
    if major_code != "closeout":
        is_complete = False

    if not milestone_label:
        milestone_label = {
            "contract": "계약 생성",
            "execution": "착수",
            "closeout": "완료" if is_complete else "준공계 제출",
        }.get(major_code, "-")

    phase_class = {
        "contract": "bg-warning text-dark",
        "execution": "bg-primary",
        "closeout": "bg-secondary" if is_complete else "bg-info text-dark",
    }.get(major_code, "bg-light text-dark")

    return {
        "stage": stage,
        "stage_label": milestone_label,
        "major_event_label": milestone_label,
        "major_code": major_code,
        "major_label": major_label,
        "filter_key": _LIST_FILTER_KEY_BY_MAJOR.get(major_code, "active"),
        "phase_class": phase_class,
        "is_complete": bool(is_complete),
    }


def contract_workflow_summaries(alias: str, contract_rows) -> dict[str, dict]:
    """Derive Contract lifecycle only from explicit milestone events.

    User-facing lifecycle:
      계약 생성 -> 계약
      착수      -> 진행
      준공계 제출 -> 준공
      완료      -> 준공 완료

    Only event types listed in CONTRACT_LIFECYCLE_MILESTONES can move the coarse
    lifecycle. `착수계` therefore does not start 진행. Contract change, period
    extension, suspend/resume, progress reports, inspection events, delivery,
    and billing/payment remain timeline history without changing the major phase.

    Contract.status is neither read nor written here. Existing status columns are
    legacy compatibility data only and can be removed later in a dedicated schema
    cleanup after all tenant/code references are verified.
    """

    contracts = {str(row.id): row for row in contract_rows}
    if not contracts:
        return {}

    latest: dict[str, tuple[int, str, str]] = {}
    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT contract_id::text, event_type
              FROM ops.process_events
             WHERE contract_id = ANY(%s::uuid[])
               AND COALESCE(status, '') <> 'void'
            """,
            [list(contracts.keys())],
        )
        for contract_id, event_type in cur.fetchall():
            event_type = str(event_type or "").strip()
            milestone = CONTRACT_LIFECYCLE_MILESTONES.get(event_type)
            if not milestone:
                continue
            stage, label = milestone
            rank = _MILESTONE_RANK[event_type]
            current = latest.get(contract_id)
            if current is None or rank > current[0]:
                latest[contract_id] = (rank, stage, label)

    result: dict[str, dict] = {}
    for contract_id in contracts:
        milestone = latest.get(contract_id)
        if milestone is None:
            result[contract_id] = _stage_summary(
                "contract",
                milestone_label="계약 생성",
            )
            continue

        _rank, stage, label = milestone
        result[contract_id] = _stage_summary(
            stage,
            is_complete=label == "완료",
            milestone_label=label,
        )
    return result


def contract_workflow_summary(alias: str, contract) -> dict:
    return contract_workflow_summaries(alias, [contract]).get(
        str(contract.id),
        _stage_summary("contract", milestone_label="계약 생성"),
    )
