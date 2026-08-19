from __future__ import annotations

from django.db import connections

from geoflow_ops.process_workflow import STAGE_CHOICES


# Business progress is intentionally separate from financial settlement.
# Billing events may continue long after the technical service is finished,
# so they must never advance or regress the contract's business phase.
_STAGE_ORDER = {
    "pre_contract": 10,
    "contract": 20,
    "kickoff": 30,
    "execution": 40,
    "inspection": 50,
    "closeout": 60,
}
_STAGE_LABELS = {choice.code: choice.label for choice in STAGE_CHOICES}
_DISPLAY_MAJOR_LABELS = {
    "contract": "계약",
    "execution": "진행",
    "closeout": "준공",
}
_CLOSEOUT_COMPLETE_EVENT_TYPES = {"closeout_complete"}


def major_phase_for_stage(stage: str | None) -> tuple[str, str]:
    """Preserve the established stage-group contract used by existing callers."""
    stage = str(stage or "").strip()
    if stage in {"pre_contract", "contract"}:
        return "contract", "계약(전)"
    if stage in {"kickoff", "execution", "inspection"}:
        return "execution", "수행(진행)"
    if stage in {"closeout", "billing"}:
        return "closeout", "준공"
    return "execution", "수행(진행)"


def fallback_stage_for_contract_status(status: str | None) -> str:
    """Legacy compatibility fallback for callers that still inspect Contract.status."""
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
) -> dict:
    stage = str(stage or "").strip() or fallback_stage_for_contract_status(contract_status)
    major_code, _legacy_major_label = major_phase_for_stage(stage)
    major_label = _DISPLAY_MAJOR_LABELS.get(major_code, _legacy_major_label)
    if major_code != "closeout":
        is_complete = False
    phase_class = {
        "contract": "bg-warning text-dark",
        "execution": "bg-primary",
        "closeout": "bg-secondary" if is_complete else "bg-info text-dark",
    }.get(major_code, "bg-light text-dark")
    return {
        "stage": stage,
        "stage_label": "준공 완료" if is_complete else _STAGE_LABELS.get(stage, stage or "-"),
        "major_code": major_code,
        "major_label": major_label,
        "phase_class": phase_class,
        "is_complete": bool(is_complete),
    }


def contract_workflow_summaries(alias: str, contract_rows) -> dict[str, dict]:
    """Return the highest reached business stage per contract.

    Contract and Project events share one event ledger. Project events carry
    contract_id lineage, so both scopes contribute to the contract's business
    phase. Contract.status remains a separate operational/compatibility value.

    New or event-less contracts are shown as 계약 regardless of Contract.status.
    Once a kickoff/execution/inspection event exists the displayed phase is 진행.
    Later contract-change/extension events cannot regress it because the highest
    reached business stage wins. Billing/settlement events are deliberately
    ignored for business-stage progression. Closeout remains visibly in progress
    until the explicit `closeout_complete` event is recorded; delivery alone is
    not final closure.
    """

    contracts = {str(row.id): row for row in contract_rows}
    if not contracts:
        return {}

    latest: dict[str, tuple[int, str]] = {}
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
        for contract_id, stage, event_type in cur.fetchall():
            stage = str(stage or "").strip()
            event_type = str(event_type or "").strip()
            if event_type in _CLOSEOUT_COMPLETE_EVENT_TYPES:
                completed_contracts.add(contract_id)
            rank = _STAGE_ORDER.get(stage, 0)
            if rank <= 0:
                continue
            current = latest.get(contract_id)
            if current is None or rank > current[0]:
                latest[contract_id] = (rank, stage)

    result: dict[str, dict] = {}
    for contract_id, contract in contracts.items():
        # Lifecycle display is event-driven. No lifecycle event means 계약,
        # even when an old/manual operational status contains another token.
        stage = latest.get(contract_id, (0, "contract"))[1]
        result[contract_id] = _stage_summary(
            stage,
            contract_status=getattr(contract, "status", None),
            is_complete=contract_id in completed_contracts,
        )
    return result


def contract_workflow_summary(alias: str, contract) -> dict:
    return contract_workflow_summaries(alias, [contract]).get(
        str(contract.id),
        _stage_summary("contract", contract_status=getattr(contract, "status", None)),
    )
