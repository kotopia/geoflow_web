from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.db import connections
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from control.gf_authz.permissions import gf_has_perm

from .models import ProcessEvent, ProcessEventAttachment, Project
from .services.entity_access import (
    authorize_scope_read,
    authorize_scope_write,
    has_scope_permission,
    require_tenant_context,
)
from .views_events import _event_payload


def _parse_uuid(value):
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _project_contract_id(alias: str, project_id: UUID):
    return (
        Project.objects.using(alias)
        .filter(pk=project_id)
        .values_list("contract_id", flat=True)
        .first()
    )


def _event_filter(request, alias: str, scope_type: str, scope_id: UUID):
    """Return the fail-closed timeline filter and mode for one business scope."""

    if scope_type == "contract":
        can_view_projects = has_scope_permission(request, "project", write=False)
        if can_view_projects:
            return (
                Q(scope_type="contract", scope_id=scope_id)
                | Q(scope_type="project", contract_id=scope_id),
                "contract_with_projects",
            )
        return Q(scope_type="contract", scope_id=scope_id), "contract_only"

    if scope_type == "project":
        base = Q(scope_type="project", scope_id=scope_id)
        contract_id = _project_contract_id(alias, scope_id)
        can_view_contracts = has_scope_permission(request, "contract", write=False)
        if contract_id and can_view_contracts:
            return (
                base | Q(scope_type="contract", scope_id=contract_id),
                "project_with_contract",
            )
        return base, "project_only"

    return Q(scope_type=scope_type, scope_id=scope_id), "scope_only"


def _assignment_name_maps(alias: str, events):
    department_ids = sorted({
        str(event.owner_department_id)
        for event in events
        if event.owner_department_id
    })
    employee_ids = sorted({
        str(event.assignee_employee_id)
        for event in events
        if event.assignee_employee_id
    })

    departments = {}
    employees = {}
    with connections[alias].cursor() as cur:
        if department_ids:
            cur.execute(
                "SELECT id::text, name FROM hr.departments WHERE id = ANY(%s::uuid[])",
                [department_ids],
            )
            departments = {row[0]: row[1] or "" for row in cur.fetchall()}
        if employee_ids:
            cur.execute(
                "SELECT id::text, name, title FROM hr.employee_profile WHERE id = ANY(%s::uuid[])",
                [employee_ids],
            )
            employees = {
                row[0]: {
                    "name": row[1] or "",
                    "title": row[2] or "",
                }
                for row in cur.fetchall()
            }
    return departments, employees


def _project_name_map(alias: str, events):
    ids = sorted({event.project_id for event in events if event.project_id})
    if not ids:
        return {}
    return {
        str(project_id): name or ""
        for project_id, name in (
            Project.objects.using(alias)
            .filter(id__in=ids)
            .values_list("id", "name")
        )
    }


def _attachment_map(alias: str, events):
    ids = [event.id for event in events]
    grouped = defaultdict(list)
    if not ids:
        return grouped
    links = (
        ProcessEventAttachment.objects.using(alias)
        .filter(event_id__in=ids)
        .select_related("attachment")
        .order_by("event_id", "ord", "created_at")
    )
    for link in links:
        attachment = link.attachment
        if attachment.deleted_at:
            continue
        grouped[str(link.event_id)].append(
            {
                "id": str(attachment.id),
                "original_name": attachment.original_name,
                "mime_type": attachment.mime_type or "",
                "size_bytes": attachment.size_bytes,
                "role": link.role,
            }
        )
    return grouped


@never_cache
@login_required
@require_GET
def workboard_event_list(request):
    alias = require_tenant_context(request)
    scope_type = str(request.GET.get("scope_type") or "").strip().lower()
    scope_id = _parse_uuid(request.GET.get("scope_id"))
    if scope_type not in {"contract", "project", "employee", "orgunit"} or scope_id is None:
        return JsonResponse({"error": "Invalid scope"}, status=400)
    if not authorize_scope_read(request, alias, scope_type, scope_id):
        return JsonResponse({"error": "Forbidden"}, status=403)

    event_filter, timeline_mode = _event_filter(request, alias, scope_type, scope_id)
    events = list(
        ProcessEvent.objects.using(alias)
        .filter(event_filter)
        .order_by("stage", "occurred_at", "created_at")
    )
    attachments = _attachment_map(alias, events)

    can_read_directory = gf_has_perm(request, "directory.view")
    if can_read_directory:
        departments, employees = _assignment_name_maps(alias, events)
    else:
        departments, employees = {}, {}

    can_view_projects = has_scope_permission(request, "project", write=False)
    projects = _project_name_map(alias, events) if can_view_projects else {}

    result = []
    for event in events:
        item = _event_payload(event, attachments=attachments.get(str(event.id), []))
        item["can_write"] = bool(
            authorize_scope_write(request, alias, event.scope_type, event.scope_id)
        )
        item["owner_department_name"] = departments.get(str(event.owner_department_id), "") if event.owner_department_id else ""
        employee = employees.get(str(event.assignee_employee_id), {}) if event.assignee_employee_id else {}
        item["assignee_employee_name"] = employee.get("name", "")
        item["assignee_employee_title"] = employee.get("title", "")
        item["project_name"] = projects.get(str(event.project_id), "") if event.project_id else ""
        result.append(item)

    scope_can_write = bool(authorize_scope_write(request, alias, scope_type, scope_id))
    return JsonResponse(
        {
            "events": result,
            "can_write": scope_can_write,
            "can_assign": bool(scope_can_write and can_read_directory),
            "timeline_mode": timeline_mode,
        }
    )


@never_cache
@login_required
@require_GET
def assignment_options(request):
    alias = require_tenant_context(request)
    scope_type = str(request.GET.get("scope_type") or "").strip().lower()
    scope_id = _parse_uuid(request.GET.get("scope_id"))
    if scope_type not in {"contract", "project"} or scope_id is None:
        return JsonResponse({"error": "Invalid scope"}, status=400)

    can_assign = bool(
        authorize_scope_write(request, alias, scope_type, scope_id)
        and gf_has_perm(request, "directory.view")
    )
    if not can_assign:
        return JsonResponse({"departments": [], "employees": [], "can_assign": False})

    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT id::text, name, org_unit_id::text
              FROM hr.departments
             WHERE active=true
             ORDER BY name
            """
        )
        departments = [
            {"id": row[0], "name": row[1] or "", "org_unit_id": row[2] or ""}
            for row in cur.fetchall()
        ]
        cur.execute(
            """
            SELECT id::text, name, title, department_id::text, status
              FROM hr.employee_profile
             WHERE status IS NULL OR status <> '퇴사'
             ORDER BY name
            """
        )
        employees = [
            {
                "id": row[0],
                "name": row[1] or "",
                "title": row[2] or "",
                "department_id": row[3] or "",
                "status": row[4] or "",
            }
            for row in cur.fetchall()
        ]

    return JsonResponse(
        {"departments": departments, "employees": employees, "can_assign": True}
    )
