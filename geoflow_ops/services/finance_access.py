"""Finance permissions shared by records, evidence and process events.

No role or contract permission implicitly grants Finance access. The central
role-permission mapping remains the only source of these two permissions.
"""
from __future__ import annotations

from django.core.exceptions import PermissionDenied

from control.gf_authz.permissions import gf_has_perm
from geoflow_ops.process_workflow import default_stage_for_event, normalize_stage


FINANCE_EVENT_STAGES = frozenset({"settlement", "billing"})
FINANCE_ATTACHMENT_PURPOSES = frozenset({"finance_invoice", "finance_evidence"})


def can_view_finance(request) -> bool:
    return request is not None and gf_has_perm(request, "finance.view")


def can_edit_finance(request) -> bool:
    return can_view_finance(request) and gf_has_perm(request, "finance.edit")


def require_finance_access(request, *, write: bool = False) -> str:
    # Imported here because entity_access also uses the event classification.
    from .entity_access import require_tenant_context

    alias = require_tenant_context(request)
    allowed = can_edit_finance(request) if write else can_view_finance(request)
    if not allowed:
        raise PermissionDenied("Permission denied")
    return alias


def is_finance_event(stage, event_type) -> bool:
    """Cover configured settlement types and historical billing vocabulary.

    Check both fields so moving a known Finance type into another stage cannot
    bypass its permission. Display labels and free-text titles are not policies.
    """
    stage = normalize_stage(str(stage or "").strip().lower())
    inferred_stage = default_stage_for_event(str(event_type or "").strip().lower())
    return stage in FINANCE_EVENT_STAGES or inferred_stage in FINANCE_EVENT_STAGES


def has_event_finance_permission(request, stage, event_type, *, write: bool) -> bool:
    if not is_finance_event(stage, event_type):
        return True
    return can_edit_finance(request) if write else can_view_finance(request)


def is_finance_attachment(attachment) -> bool:
    meta = getattr(attachment, "meta", None)
    return bool(
        getattr(attachment, "purpose", None) in FINANCE_ATTACHMENT_PURPOSES
        or (isinstance(meta, dict) and meta.get("finance_record_type"))
    )
