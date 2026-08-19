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
_LIFECYCLE_STAGES = {"kickoff", "execution", "inspection", "closeout"}
_LIFECYCLE_EVENT_TYPES = {"contract_cancel", "closeout_complete"}


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


def event_affects_contract_lifecycle(stage: str | None, event_type: str | None) -> bool:
    return (
        str(stage or "").strip() in _LIFECYCLE_STAGES
        or str(event_type or "").strip() in _LIFECYCLE_EVENT_TYPES
    )


def _stage_summary(
    stage: str | None,
    *,
    contract_status: str | None = None,
    is_final_complete: bool = False,
    canceled: bool = False,
) -> dict:
    status_text = str(contract_status or "").strip().lower()
    legacy_canceled = status_text in {"cancel", "canceled", "cancelled", "취소"}
    if canceled or legacy_canceled:
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
    # treated as final when their stored legacy status already says complete.
    legacy_final = status_text in {"complete", "completed", "완료", "준공"}
    final_complete = bool(is_final_complete)
    if major_code == "closeout" and legacy_final and not is_final_complete:
        final_complete = True

    closeout_label = ""
    if major_code == "closeout":
        closeout_label = "준공완료" if final_complete else "준공 진행"
        major_label = "✓ 준공완료" if final_complete else "준공 진행"

    return {
        "stage": stage,
        "stage_label": _STAGE_LABELS.get(stage, stage or "-"),
        "major_code": major_code,
        "major_label": major_label,
        "lifecycle_status": lifecycle_status_for_major(major_code),
        "is_final_complete": final_complete,
        "closeout_label": closeout_label,
    }


def _event_lifecycle_state(alias: str, contract_id) -> tuple[str, bool]:
    """Return canonical Contract.status and final-complete flag from events only."""
    latest_rank = 0
    canceled = False
    final_complete = False

    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT stage, event_type
              FROM ops.process_events
             WHERE contract_id=%s
               AND COALESCE(status, '') <> 'void'
            """,
            [str(contract_id)],
        )
        for stage, event_type in cur.fetchall():
            stage = str(stage or "").strip()
            event_type = str(event_type or "").strip()
            if event_type == "contract_cancel":
                canceled = True
            if event_type == "closeout_complete":
                final_complete = True
            if stage == "billing":
                continue
            latest_rank = max(latest_rank, _STAGE_ORDER.get(stage, 0))

    if canceled:
        return "cancel", False
    if latest_rank >= _STAGE_ORDER["closeout"]:
        return "complete", final_complete
    if latest_rank >= _STAGE_ORDER["kickoff"]:
        return "active", False
    return "planned", False


def sync_contract_status_from_events(alias: str, contract_id) -> str | None:
    """Synchronize the legacy Contract.status column from milestone events.

    The column remains for compatibility with existing reports and filters, but
    users no longer edit it directly. Contract-change, extension, suspend/resume,
    and billing events do not move the lifecycle backwards or forwards by
    themselves because only lifecycle-affecting event mutations call this helper.
    """
    if not contract_id:
        return None
    target, _final_complete = _event_lifecycle_state(alias, contract_id)
    with connections[alias].cursor() as cur:
        cur.execute(
            """
            UPDATE ctr.contracts
               SET status=%s, updated_at=now()
             WHERE id=%s
               AND COALESCE(status, '') <> %s
            """,
            [target, str(contract_id), target],
        )
    return target


def contract_workflow_summaries(alias: str, contract_rows) -> dict[str, dict]:
    """Derive contract lifecycle from the shared non-void event ledger.

    Lifecycle is deliberately coarse and monotonic for normal work:
    계약 -> 진행 -> 준공. Contract-change/extension/suspend/resume events remain
    history inside the current phase and never move the lifecycle backwards.
    Billing events never advance technical lifecycle. An explicit non-void
    `closeout_complete` event marks a closeout contract as finally completed.

    Legacy compatibility matters: contract/pre-contract/billing-only events do
    not replace an already stored lifecycle. Only a true lifecycle milestone
    (착수/수행/검사/준공 or terminal event) switches the summary to event-driven
    calculation.
    """

    contracts = {str(row.id): row for row in contract_rows}
    if not contracts:
        return {}

    latest_stage: dict[str, tuple[int, str]] = {}
    final_complete: set[str] = set()
    canceled: set[str] = set()
    has_lifecycle_event: set[str] = set()

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
                has_lifecycle_event.add(contract_id)
                continue
            if event_type == "closeout_complete":
                final_complete.add(contract_id)
                has_lifecycle_event.add(contract_id)

            # Financial and contract-administration events remain visible in the
            # timeline but never establish or regress the technical lifecycle.
            if stage not in _LIFECYCLE_STAGES:
                continue

            has_lifecycle_event.add(contract_id)
            rank = _STAGE_ORDER.get(stage, 0)
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

        if contract_id in has_lifecycle_event:
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
