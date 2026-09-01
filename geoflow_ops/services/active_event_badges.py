from __future__ import annotations

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date

from geoflow_ops.models import ProcessEvent, Project
from geoflow_ops.process_workflow import DEFAULT_HIGHLIGHT_DAYS, EVENT_TYPE_CHOICES


_EVENT_TYPE_LABELS = {choice.code: choice.label for choice in EVENT_TYPE_CHOICES}


def _highlight_active(event) -> bool:
    payload = event.payload if isinstance(event.payload, dict) else {}
    display = dict(payload.get("display") or {})
    if not bool(display.get("highlight_enabled", False)) or event.status == "void":
        return False
    today = timezone.localdate()
    occurred = event.occurred_at or (event.created_at.date() if event.created_at else today)
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


def active_event_labels_for_contracts(alias: str, contract_ids) -> dict[str, list[str]]:
    """Return active event labels using both canonical and legacy lineage.

    Older ProcessEvent rows can have contract_id/project_id unset while their
    scope_type/scope_id still points at the contract or project. Detail APIs read
    by scope, so list summaries must resolve the same rows instead of relying on
    contract_id alone.
    """
    ids = [str(value) for value in contract_ids if value]
    if not ids:
        return {}

    project_rows = Project.objects.using(alias).filter(contract_id__in=ids).values_list("id", "contract_id")
    project_to_contract = {str(project_id): str(contract_id) for project_id, contract_id in project_rows}
    project_ids = list(project_to_contract)

    query = Q(contract_id__in=ids) | Q(scope_type="contract", scope_id__in=ids)
    if project_ids:
        query |= Q(scope_type="project", scope_id__in=project_ids)

    labels: dict[str, list[str]] = {contract_id: [] for contract_id in ids}
    events = (
        ProcessEvent.objects.using(alias)
        .filter(query)
        .exclude(status="void")
        .only("contract_id", "scope_type", "scope_id", "event_type", "occurred_at", "payload", "status", "created_at")
        .order_by("occurred_at", "created_at")
    )
    for event in events:
        contract_id = str(event.contract_id) if event.contract_id and str(event.contract_id) in labels else None
        if contract_id is None and event.scope_type == "contract" and str(event.scope_id) in labels:
            contract_id = str(event.scope_id)
        if contract_id is None and event.scope_type == "project":
            contract_id = project_to_contract.get(str(event.scope_id))
        if not contract_id or not _highlight_active(event):
            continue
        label = _EVENT_TYPE_LABELS.get(str(event.event_type or "").strip(), str(event.event_type or "").strip())
        if label and label not in labels[contract_id]:
            labels[contract_id].append(label)
    return labels
