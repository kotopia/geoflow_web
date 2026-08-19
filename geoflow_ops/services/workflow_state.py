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
_CLOSEOUT_COMPLETE_EVENT_TYPES = {"delivery", "closeout_complete"}


def major_phase_for_stage(stage: str | None) -> tuple[str, str]:
    stage = str(stage or "").strip()
    if stage in {"pre_contract", "contract"}:
        return "contract", "계약"
    if stage in {"kickoff", "execution", "inspection"}:
        return "execution", "진행"
    if stage == "closeout":
        return "closeout", "준공"
    # Unknown/custom stages do not silently move a contract to completion.
    return "contract", "계약"


def fallback_stage_for_contract_status(status: str | None) -> str:
    """Return the safe initial business stage when no workflow event exists.

    Contract.status is an operational flag (pause/cancel/etc.), not the business
    workflow phase. A newly created or legacy event-less contract therefore
    remains in the contract phase until a kickoff/execution event is recorded.
    """

    return "contract"


def _stage_summary(
    stage: str | None,
    *,
    contract_status: str | None = None,
    is_complete: bool = False,
) -> dict:
    stage = str(stage or "").strip() or fallback_stage_for_contract_status(contract_status)
    major_code, major_label = major_phase_for_stage(stage)
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
    phase. Contract.status remains a separate operational flag.

    Billing/settlement events are deliberately ignored for business-stage
    progression. A closeout phase becomes visually complete only after an
    explicit completion event (currently delivery, with closeout_complete kept
    as a forward-compatible configurable event code).
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
        stage = latest.get(contract_id, (0, ""))[1]
        result[contract_id] = _stage_summary(
            stage,
            contract_status=getattr(contract, "status", None),
            is_complete=contract_id in completed_contracts,
        )
    return result


def contract_workflow_summary(alias: str, contract) -> dict:
    return contract_workflow_summaries(alias, [contract]).get(
        str(contract.id),
        _stage_summary(None, contract_status=getattr(contract, "status", None)),
    )
