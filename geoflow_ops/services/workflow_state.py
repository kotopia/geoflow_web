from __future__ import annotations

from django.db import connections

from geoflow_ops.process_workflow import STAGE_CHOICES


# Billing is intentionally excluded. Financial collection continues after the
# technical service can already be in closeout/completed state.
_STAGE_ORDER = {
    "pre_contract": 10,
    "contract": 20,
    "kickoff": 30,
    "execution": 40,
    "inspection": 50,
    "closeout": 60,
}
_STAGE_LABELS = {choice.code: choice.label for choice in STAGE_CHOICES}


def major_phase_for_stage(stage: str | None) -> tuple[str, str]:
    stage = str(stage or "").strip()
    if stage in {"pre_contract", "contract"}:
        return "contract", "계약"
    if stage in {"kickoff", "execution", "inspection"}:
        return "execution", "진행"
    if stage == "closeout":
        return "closeout", "준공"
    return "contract", "계약"


def fallback_stage_for_contract_status(status: str | None) -> str:
    status = str(status or "").strip().lower()
    if status in {"complete", "completed", "완료", "준공"}:
        return "closeout"
    if status in {"active", "진행", "진행중", "pause", "paused", "중지", "보류"}:
        return "execution"
    return "contract"


def lifecycle_status_for_major(major_code: str) -> str:
    return {
        "contract": "planned",
        "execution": "active",
        "closeout": "complete",
        "cancel": "cancel",
    }.get(str(major_code or ""), "planned")


def _stage_summary(
    stage: str | None,
    *,
    contract_status: str | None = None,
    is_final_complete: bool = False,
    canceled: bool = False,
) -> dict:
    status_text = str(contract_status or "").strip().lower()
    if canceled:
        return {
            "stage": "contract",
            "stage_label": "계약취소",
            "major_code": "cancel",
            "major_label": "취소",
            "lifecycle_status": "cancel",
            "is_final_complete": False,
            "closeout_label": "",
        }

    stage = str(stage or "").strip() or fallback_stage_for_contract_status(contract_status)
    major_code, major_label = major_phase_for_stage(stage)

    # Existing completed contracts from before the explicit 준공완료 event are
    # treated as final only when the stored legacy status already says complete.
    legacy_final = status_text in {"complete", "completed", "완료", "준공"}
    final_complete = bool(is_final_complete or (not stage and legacy_final))
    if major_code == "closeout" and legacy_final and not is_final_complete:
        final_complete = True

    return {
        "stage": stage,
        "stage_label": _STAGE_LABELS.get(stage, stage or "-"),
        "major_code": major_code,
        "major_label": major_label,
        "lifecycle_status": lifecycle_status_for_major(major_code),
        "is_final_complete": final_complete,
        "closeout_label": (
            "준공완료" if major_code == "closeout" and final_complete
            else "준공 진행" if major_code == "closeout"
            else ""
        ),
    }


def contract_workflow_summaries(alias: str, contract_rows) -> dict[str, dict]:
    """Derive contract lifecycle from the shared non-void event ledger.

    Lifecycle is deliberately coarse and monotonic for normal work:
    계약 -> 진행 -> 준공. Contract-change/extension/suspend/resume events remain
    history inside the current phase and never move the lifecycle backwards.
    Billing events never advance technical lifecycle. An explicit non-void
    `closeout_complete` event marks a closeout contract as finally completed.
    """

    contracts = {str(row.id): row for row in contract_rows}
    if not contracts:
        return {}

    latest_stage: dict[str, tuple[int, str]] = {}
    final_complete: set[str] = set()
    canceled: set[str] = set()
    has_business_event: set[str] = set()

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

            if event_type == "contract_cancel":
                canceled.add(contract_id)
                has_business_event.add(contract_id)
                continue
            if event_type == "closeout_complete":
                final_complete.add(contract_id)

            # Financial events are still retained in the timeline, but they are
            # intentionally ignored for the technical contract lifecycle.
            if stage == "billing":
                continue

            rank = _STAGE_ORDER.get(stage, 0)
            if rank <= 0:
                continue
            has_business_event.add(contract_id)
            current = latest_stage.get(contract_id)
            if current is None or rank > current[0]:
                latest_stage[contract_id] = (rank, stage)

    result: dict[str, dict] = {}
    for contract_id, contract in contracts.items():
        stored_status = getattr(contract, "status", None)
        if contract_id in canceled:
            result[contract_id] = _stage_summary(
                None,
                contract_status=stored_status,
                canceled=True,
            )
            continue

        if contract_id in has_business_event:
            stage = latest_stage.get(contract_id, (0, "contract"))[1]
            # For event-driven contracts final completion is explicit only.
            result[contract_id] = _stage_summary(
                stage,
                contract_status=None,
                is_final_complete=contract_id in final_complete,
            )
        else:
            result[contract_id] = _stage_summary(
                None,
                contract_status=stored_status,
                is_final_complete=False,
            )
    return result


def contract_workflow_summary(alias: str, contract) -> dict:
    return contract_workflow_summaries(alias, [contract]).get(
        str(contract.id),
        _stage_summary(None, contract_status=getattr(contract, "status", None)),
    )
