from __future__ import annotations

from collections import defaultdict

from django.db import connections

from geoflow_ops.process_workflow import STAGE_CHOICES


_STAGE_ORDER = {
    "pre_contract": 10,
    "contract": 20,
    "kickoff": 30,
    "execution": 40,
    "inspection": 50,
    "closeout": 60,
    "billing": 70,
}
_STAGE_LABELS = {choice.code: choice.label for choice in STAGE_CHOICES}


def major_phase_for_stage(stage: str | None) -> tuple[str, str]:
    stage = str(stage or "").strip()
    if stage in {"pre_contract", "contract"}:
        return "contract", "계약(전)"
    if stage in {"kickoff", "execution", "inspection"}:
        return "execution", "수행(진행)"
    if stage in {"closeout", "billing"}:
        return "closeout", "준공"
    return "execution", "수행(진행)"


def fallback_stage_for_contract_status(status: str | None) -> str:
    status = str(status or "").strip().lower()
    if status in {"planned", "계약전"}:
        return "pre_contract"
    if status in {"complete", "completed", "완료"}:
        return "closeout"
    return "execution"


def _stage_summary(stage: str | None, *, contract_status: str | None = None) -> dict:
    stage = str(stage or "").strip() or fallback_stage_for_contract_status(contract_status)
    major_code, major_label = major_phase_for_stage(stage)
    return {
        "stage": stage,
        "stage_label": _STAGE_LABELS.get(stage, stage or "-"),
        "major_code": major_code,
        "major_label": major_label,
    }


def contract_workflow_summaries(alias: str, contract_rows) -> dict[str, dict]:
    """Return the highest reached non-void workflow stage per contract.

    Contract and Project events share one event ledger. Project events carry
    contract_id lineage, so both scopes contribute to the contract's business
    stage without conflating Project execution status with Contract.status.
    """

    contracts = {str(row.id): row for row in contract_rows}
    if not contracts:
        return {}

    latest: dict[str, tuple[int, str]] = {}
    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT contract_id::text, stage
              FROM ops.process_events
             WHERE contract_id = ANY(%s::uuid[])
               AND COALESCE(status, '') <> 'void'
            """,
            [list(contracts.keys())],
        )
        for contract_id, stage in cur.fetchall():
            rank = _STAGE_ORDER.get(str(stage or "").strip(), 0)
            current = latest.get(contract_id)
            if current is None or rank > current[0]:
                latest[contract_id] = (rank, str(stage or "").strip())

    result: dict[str, dict] = {}
    for contract_id, contract in contracts.items():
        stage = latest.get(contract_id, (0, ""))[1]
        result[contract_id] = _stage_summary(stage, contract_status=getattr(contract, "status", None))
    return result


def contract_workflow_summary(alias: str, contract) -> dict:
    return contract_workflow_summaries(alias, [contract]).get(
        str(contract.id),
        _stage_summary(None, contract_status=getattr(contract, "status", None)),
    )
