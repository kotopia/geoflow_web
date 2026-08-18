from __future__ import annotations

import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from control.gf_authz.permissions import gf_has_perm

from . import views_events, views_workboard
from .models import ProcessEvent
from .process_workflow import default_stage_for_event, normalize_stage
from .services.entity_access import require_tenant_context
from .services.tenant_settings import (
    event_type_allowed,
    event_workflow_options,
    settings_codes,
)


ASSIGNMENT_FIELDS = {"owner_department_id", "assignee_employee_id"}


def _payload(request):
    try:
        data = json.loads(request.body or b"{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _payload_contains_assignment_write(request) -> bool:
    data = _payload(request)
    return isinstance(data, dict) and bool(ASSIGNMENT_FIELDS.intersection(data))


def _assignment_write_forbidden(request) -> bool:
    return _payload_contains_assignment_write(request) and not gf_has_perm(
        request, "directory.view"
    )


def _workflow_error(alias: str, data: dict, *, existing=None, creating: bool):
    if creating:
        event_type = str(data.get("event_type") or "").strip()
        stage = normalize_stage(data.get("stage"))
        if not stage and event_type:
            stage = default_stage_for_event(event_type) or ""
        status = str(data.get("status") or "open").strip()

        if stage not in settings_codes(alias, "event.stage"):
            return "Invalid stage"
        if status not in settings_codes(alias, "event.status"):
            return "Invalid status"
        if not event_type_allowed(alias, stage, event_type):
            return "Invalid event type for stage"
        return None

    if existing is None:
        return None

    existing_stage = normalize_stage(existing.stage)
    existing_type = str(existing.event_type or "").strip()
    existing_status = str(existing.status or "").strip()

    incoming_stage = normalize_stage(data.get("stage")) if "stage" in data else existing_stage
    incoming_type = str(data.get("event_type") or "").strip() if "event_type" in data else existing_type
    incoming_status = str(data.get("status") or "").strip() if "status" in data else existing_status

    stage_changed = incoming_stage != existing_stage
    type_changed = incoming_type != existing_type
    status_changed = incoming_status != existing_status

    # Existing historical/custom combinations remain editable for unrelated
    # fields. The configured workflow is enforced only when the workflow value
    # actually changes, not merely because the UI resubmits the current value.
    if stage_changed or type_changed:
        if incoming_stage not in settings_codes(alias, "event.stage"):
            return "Invalid stage"
        if not event_type_allowed(alias, incoming_stage, incoming_type):
            return "Invalid event type for stage"

    if status_changed and incoming_status not in settings_codes(alias, "event.status"):
        return "Invalid status"
    return None


@never_cache
@login_required
@require_GET
def event_list(request):
    require_tenant_context(request)
    return views_workboard.workboard_event_list(request)


@never_cache
@login_required
@require_GET
def workflow_options(request):
    alias = require_tenant_context(request)
    options = event_workflow_options(alias)
    return JsonResponse(
        {
            "stages": [
                {"code": code, "label": label}
                for code, label in options["stages"]
            ],
            "statuses": [
                {"code": code, "label": label}
                for code, label in options["statuses"]
            ],
            "types_by_stage": {
                stage: [
                    {"code": code, "label": label}
                    for code, label in rows
                ]
                for stage, rows in options["types_by_stage"].items()
            },
        }
    )


@login_required
@require_POST
def event_create(request):
    alias = require_tenant_context(request)
    if _assignment_write_forbidden(request):
        return JsonResponse({"error": "Forbidden"}, status=403)

    data = _payload(request)
    if data is not None:
        error = _workflow_error(alias, data, creating=True)
        if error:
            return JsonResponse({"error": error}, status=400)
    return views_events.create_event(request)


@login_required
@require_POST
def event_update(request, event_id):
    alias = require_tenant_context(request)
    if _assignment_write_forbidden(request):
        return JsonResponse({"error": "Forbidden"}, status=403)

    data = _payload(request)
    if data is not None:
        existing = ProcessEvent.objects.using(alias).filter(pk=event_id).first()
        error = _workflow_error(
            alias,
            data,
            existing=existing,
            creating=False,
        )
        if error:
            return JsonResponse({"error": error}, status=400)
    return views_events.update_event(request, event_id)
