from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from geoflow_ops.models import ProcessEvent
from geoflow_ops.process_workflow import normalize_stage
from geoflow_ops.services.tenant_settings import normalize_contract_status


MAJOR_PHASES = (
    ("contract", "계약(전)"),
    ("execution", "수행(진행)"),
    ("closeout", "준공"),
)
MAJOR_PHASE_LABELS = dict(MAJOR_PHASES)

# Billing is intentionally auxiliary. An advance-payment or invoice event must
# never advance the contract's main execution phase by itself.
STAGE_MAJOR_PHASE = {
    "pre_contract": "contract",
    "contract": "contract",
    "kickoff": "contract",
    "execution": "execution",
    "inspection": "closeout",
    "closeout": "closeout",
}
MAJOR_PHASE_RANK = {"contract": 10, "execution": 20, "closeout": 30}
STATUS_FALLBACK_PHASE = {
    "planned": "contract",
    "active": "execution",
    "pause": "execution",
    "complete": "closeout",
    "cancel": "contract",
}


@dataclass(frozen=True)
class ContractWorkflowState:
    contract_id: str
    major_phase: str
    major_label: str
    detail_stage: str
    detail_label: str
    source: str


def _stage_label(stage: str) -> str:
    return {
        "pre_contract": "계약전",
        "contract": "계약",
        "kickoff": "착수",
        "execution": "수행",
        "inspection": "검사",
        "closeout": "준공",
        "billing": "청구/정산",
    }.get(stage, stage or "미등록")


def _major_phase_for_event(event) -> str | None:
    stage = normalize_stage(event.stage)
    # "착수계" is management administration and stays in the Contract phase.
    # The actual project "착수" event means execution has started.
    if stage == "kickoff" and str(event.event_type or "").strip() == "kickoff":
        return "execution"
    return STAGE_MAJOR_PHASE.get(stage)


def _fallback(contract_id: str, status: object) -> ContractWorkflowState:
    normalized = normalize_contract_status(status)
    major = STATUS_FALLBACK_PHASE.get(normalized, "contract")
    return ContractWorkflowState(
        contract_id=str(contract_id),
        major_phase=major,
        major_label=MAJOR_PHASE_LABELS[major],
        detail_stage="",
        detail_label="이벤트 미등록",
        source="contract_status",
    )


def contract_workflow_states(alias: str, contracts: Iterable[object]) -> dict[str, ContractWorkflowState]:
    """Compute one shared-event workflow state per contract in one query.

    Project-scoped events participate through their contract_id lineage. Void
    events are ignored. Auxiliary billing events may be the latest detail event,
    but they do not advance the three-step major flow.
    """

    contract_rows = list(contracts)
    contract_ids = [str(getattr(row, "id")) for row in contract_rows if getattr(row, "id", None)]
    result = {
        str(row.id): _fallback(str(row.id), getattr(row, "status", ""))
        for row in contract_rows
        if getattr(row, "id", None)
    }
    if not contract_ids:
        return result

    events = list(
        ProcessEvent.objects.using(alias)
        .filter(contract_id__in=contract_ids)
        .exclude(status="void")
        .only("contract_id", "stage", "event_type", "status", "occurred_at", "created_at")
        .order_by("contract_id", "occurred_at", "created_at")
    )
    grouped = defaultdict(list)
    for event in events:
        grouped[str(event.contract_id)].append(event)

    for contract_id, rows in grouped.items():
        major = None
        major_rank = -1
        for event in rows:
            candidate = _major_phase_for_event(event)
            if not candidate:
                continue
            rank = MAJOR_PHASE_RANK[candidate]
            if rank > major_rank:
                major = candidate
                major_rank = rank

        latest = rows[-1]
        detail_stage = normalize_stage(latest.stage)
        fallback_state = result.get(contract_id)
        if major is None:
            major = fallback_state.major_phase if fallback_state else "contract"
        result[contract_id] = ContractWorkflowState(
            contract_id=contract_id,
            major_phase=major,
            major_label=MAJOR_PHASE_LABELS[major],
            detail_stage=detail_stage,
            detail_label=_stage_label(detail_stage),
            source="event",
        )
    return result


def contract_workflow_state(alias: str, contract: object) -> ContractWorkflowState:
    return contract_workflow_states(alias, [contract])[str(contract.id)]
