from __future__ import annotations

import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from control.gf_authz.permissions import gf_has_perm

from . import views_events, views_workboard
from .services.entity_access import require_tenant_context


ASSIGNMENT_FIELDS = {"owner_department_id", "assignee_employee_id"}


def _payload_contains_assignment_write(request) -> bool:
    """Detect assignment mutations without weakening the canonical event parser."""

    try:
        data = json.loads(request.body or b"{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    return isinstance(data, dict) and bool(ASSIGNMENT_FIELDS.intersection(data))


def _assignment_write_forbidden(request) -> bool:
    return _payload_contains_assignment_write(request) and not gf_has_perm(
        request, "directory.view"
    )


@never_cache
@login_required
@require_GET
def event_list(request):
    """Return the cross-department tenant workboard timeline without caching."""

    require_tenant_context(request)
    return views_workboard.workboard_event_list(request)


@login_required
@require_POST
def event_create(request):
    """Guard assignment writes with tenant-directory read permission."""

    require_tenant_context(request)
    if _assignment_write_forbidden(request):
        return JsonResponse({"error": "Forbidden"}, status=403)
    return views_events.create_event(request)


@login_required
@require_POST
def event_update(request, event_id):
    """Guard assignment changes before delegating to the canonical event API."""

    require_tenant_context(request)
    if _assignment_write_forbidden(request):
        return JsonResponse({"error": "Forbidden"}, status=403)
    return views_events.update_event(request, event_id)
