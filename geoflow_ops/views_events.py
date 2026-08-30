"""Tenant process-event JSON API."""
from __future__ import annotations

import json
import logging
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.db import connections
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET, require_POST

from .models import ProcessEvent, ProcessEventAttachment, Project
from .process_workflow import default_stage_for_event, normalize_stage
from .services.department_routing import (
    default_owner_department_id,
    department_allowed_for_scope,
    route_project_inspection_request_to_management,
)
from .services.entity_access import (
    authorize_scope_read,
    authorize_scope_write,
    get_event_for_access,
    has_scope_permission,
    require_tenant_context,
)

logger = logging.getLogger(__name__)

ALLOWED_SCOPE_TYPES = {"contract", "project", "employee", "orgunit"}
ALLOWED_STATUSES = {"draft", "open", "done", "void"}
MAX_TITLE_LENGTH = ProcessEvent._meta.get_field("title").max_length or 255
MAX_STAGE_LENGTH = ProcessEvent._meta.get_field("stage").max_length or 50
MAX_EVENT_TYPE_LENGTH = ProcessEvent._meta.get_field("event_type").max_length or 50
MAX_MEMO_LENGTH = 10000
MAX_PAYLOAD_BYTES = 32768


def _json_error(message: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"error": message}, status=status)


def _parse_json(request):
    try:
        value = json.loads(request.body or b"{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _parse_uuid(value):
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _clean_text(value, *, max_length: int, field: str):
    if value is None:
        return "", None
    text = str(value)
    if len(text) > max_length:
        return None, f"{field} is too long"
    return text, None


def _clean_date(value, field: str):
    if value in (None, ""):
        return None, None
    parsed = parse_date(str(value))
    if parsed is None:
        return None, f"{field} must be YYYY-MM-DD"
    return parsed, None


def _clean_optional_uuid(value, field: str):
    if value in (None, ""):
        return None, None
    parsed = _parse_uuid(value)
    if parsed is None:
        return None, f"{field} must be UUID"
    return parsed, None


def _clean_payload(value):
    if value in (None, ""):
        return {}, None
    if not isinstance(value, dict):
        return None, "payload must be an object"
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError):
        return None, "payload must be JSON serializable"
    if len(encoded) > MAX_PAYLOAD_BYTES:
        return None, "payload is too large"
    return value, None


def _assignment_target_exists(alias: str, table: str, target_id: UUID) -> bool:
    if table not in {"hr.departments", "hr.employee_profile"}:
        return False
    with connections[alias].cursor() as cur:
        active_clause = " AND is_deleted=false" if table == "hr.employee_profile" else ""
        cur.execute(f"SELECT 1 FROM {table} WHERE id = %s{active_clause} LIMIT 1", [target_id])
        return cur.fetchone() is not None


def _derive_lineage(alias: str, scope_type: str, scope_id: UUID):
    if scope_type == "contract":
        return scope_id, None
    if scope_type == "project":
        project = (
            Project.objects.using(alias)
            .filter(pk=scope_id)
            .only("id", "contract_id")
            .first()
        )
        if not project:
            return None, None
        return project.contract_id, project.id
    return None, None


def _validate_mutable_fields(data, *, creating: bool, alias: str):
    cleaned = {}
    for name, limit in (
        ("stage", MAX_STAGE_LENGTH),
        ("event_type", MAX_EVENT_TYPE_LENGTH),
        ("title", MAX_TITLE_LENGTH),
        ("memo", MAX_MEMO_LENGTH),
    ):
        if creating or name in data:
            value, error = _clean_text(data.get(name, ""), max_length=limit, field=name)
            if error:
                return None, error
            cleaned[name] = value

    if "stage" in cleaned:
        cleaned["stage"] = normalize_stage(cleaned["stage"])

    if creating:
        event_type = cleaned.get("event_type") or ""
        if not cleaned.get("stage"):
            cleaned["stage"] = default_stage_for_event(event_type) or ""
        if not cleaned.get("stage") or not event_type:
            return None, "stage and event_type are required"

    if creating or "status" in data:
        # Status is secondary. New events always enter the active queue; a
        # stale/default draft value from older clients is normalized to open.
        status = str(data.get("status") or "open")
        if creating and status == "draft":
            status = "open"
        if status not in ALLOWED_STATUSES:
            return None, "Invalid status"
        cleaned["status"] = status

    for name in ("occurred_at", "due_at"):
        if creating or name in data:
            value, error = _clean_date(data.get(name), name)
            if error:
                return None, error
            cleaned[name] = value

    assignment_fields = (
        ("owner_department_id", "hr.departments"),
        ("assignee_employee_id", "hr.employee_profile"),
    )
    for name, table in assignment_fields:
        if creating or name in data:
            value, error = _clean_optional_uuid(data.get(name), name)
            if error:
                return None, error
            if value is not None and not _assignment_target_exists(alias, table, value):
                return None, f"Invalid {name}"
            cleaned[name] = value

    if creating or "payload" in data:
        value, error = _clean_payload(data.get("payload"))
        if error:
            return None, error
        cleaned["payload"] = value

    return cleaned, None


def _event_payload(event, *, attachments=None):
    attachments = attachments or []
    return {
        "id": str(event.id),
        "scope_type": event.scope_type,
        "scope_id": str(event.scope_id),
        "contract_id": str(event.contract_id) if event.contract_id else None,
        "project_id": str(event.project_id) if event.project_id else None,
        "owner_department_id": str(event.owner_department_id) if event.owner_department_id else None,
        "assignee_employee_id": str(event.assignee_employee_id) if event.assignee_employee_id else None,
        "stage": event.stage,
        "event_type": event.event_type,
        "title": event.title,
        "memo": event.memo,
        "status": event.status,
        "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
        "due_at": event.due_at.isoformat() if event.due_at else None,
        "payload": event.payload or {},
        "created_at": event.created_at.isoformat() if event.created_at else None,
        "updated_at": event.updated_at.isoformat() if event.updated_at else None,
        "created_by": event.created_by,
        "attachment_count": len(attachments),
        "attachments": attachments,
    }


@login_required
@require_POST
def create_event(request):
    try:
        alias = require_tenant_context(request)
    except Exception:
        return _json_error("Forbidden", status=403)
    data = _parse_json(request)
    if data is None:
        return _json_error("Invalid JSON")
    scope_type = str(data.get("scope_type") or "").strip().lower()
    scope_id = _parse_uuid(data.get("scope_id"))
    if scope_type not in ALLOWED_SCOPE_TYPES or scope_id is None:
        return _json_error("Invalid scope")
    if not authorize_scope_write(request, alias, scope_type, scope_id):
        return _json_error("Forbidden", status=403)
    cleaned, error = _validate_mutable_fields(data, creating=True, alias=alias)
    if error:
        return _json_error(error)
    contract_id, project_id = _derive_lineage(alias, scope_type, scope_id)
    if scope_type == "project" and project_id is None:
        return _json_error("Invalid scope")

    owner_department_id = cleaned.get("owner_department_id")
    if (
        scope_type in {"contract", "project"}
        and owner_department_id is not None
        and not department_allowed_for_scope(
            alias, scope_type, scope_id, owner_department_id
        )
    ):
        return _json_error("Invalid owner_department_id")

    if not owner_department_id:
        default_department = default_owner_department_id(
            alias,
            request,
            event_type=cleaned.get("event_type") or "",
            scope_type=scope_type,
            scope_id=scope_id,
        )
        if (
            default_department
            and (
                scope_type not in {"contract", "project"}
                or department_allowed_for_scope(
                    alias, scope_type, scope_id, default_department
                )
            )
        ):
            cleaned["owner_department_id"] = UUID(default_department)
    user_name = getattr(request.user, "username", None) or getattr(request.user, "email", None) or "unknown"
    try:
        event = ProcessEvent.objects.using(alias).create(
            scope_type=scope_type, scope_id=scope_id, contract_id=contract_id,
            project_id=project_id, created_by=user_name, **cleaned,
        )
    except Exception:
        logger.exception("event create failed")
        return _json_error("Failed to create event", status=500)
    payload = _event_payload(event)
    return JsonResponse({"event_id": str(event.id), "event": payload, **payload})


@login_required
@require_GET
def list_events(request):
    try:
        alias = require_tenant_context(request)
    except Exception:
        return _json_error("Forbidden", status=403)
    scope_type = str(request.GET.get("scope_type") or "").strip().lower()
    scope_id = _parse_uuid(request.GET.get("scope_id"))
    if scope_type not in ALLOWED_SCOPE_TYPES or scope_id is None:
        return _json_error("Invalid scope")
    if not authorize_scope_read(request, alias, scope_type, scope_id):
        return _json_error("Forbidden", status=403)
    try:
        events = list(ProcessEvent.objects.using(alias).filter(scope_type=scope_type, scope_id=scope_id).order_by("stage", "occurred_at", "created_at"))
        result = []
        for event in events:
            links = ProcessEventAttachment.objects.using(alias).filter(event=event).select_related("attachment").order_by("ord", "created_at")
            attachments = []
            for link in links:
                att = link.attachment
                if att.deleted_at:
                    continue
                attachments.append({"id": str(att.id), "original_name": att.original_name, "mime_type": att.mime_type or "", "size_bytes": att.size_bytes, "role": link.role})
            result.append(_event_payload(event, attachments=attachments))
    except Exception:
        logger.exception("event list failed")
        return _json_error("Failed to list events", status=500)
    can_write = has_scope_permission(request, scope_type, write=True)
    return JsonResponse({"events": result, "can_write": bool(can_write)})


@login_required
@require_POST
def update_event(request, event_id):
    try:
        alias = require_tenant_context(request)
    except Exception:
        return _json_error("Forbidden", status=403)
    event = get_event_for_access(request, alias, event_id, write=True)
    if not event:
        return _json_error("Forbidden", status=403)
    data = _parse_json(request)
    if data is None:
        return _json_error("Invalid JSON")
    cleaned, error = _validate_mutable_fields(data, creating=False, alias=alias)
    if error:
        return _json_error(error)

    if "owner_department_id" in cleaned:
        incoming_department_id = cleaned.get("owner_department_id")
        if (
            event.scope_type in {"contract", "project"}
            and incoming_department_id is not None
            and incoming_department_id != event.owner_department_id
            and not department_allowed_for_scope(
                alias,
                event.scope_type,
                event.scope_id,
                incoming_department_id,
            )
        ):
            return _json_error("Invalid owner_department_id")

    for key, value in cleaned.items():
        setattr(event, key, value)
    if event.scope_type == "project" and event.event_type == "inspection_request" and event.status == "done":
        management_department = route_project_inspection_request_to_management(alias, event.scope_id)
        if management_department:
            event.owner_department_id = UUID(management_department)
    try:
        event.save(using=alias)
    except Exception:
        logger.exception("event update failed")
        return _json_error("Failed to update event", status=500)
    return JsonResponse({"success": True, "event_id": str(event.id)})


@login_required
@require_POST
def delete_event(request, event_id):
    """Void an event instead of erasing cross-department business history."""
    try:
        alias = require_tenant_context(request)
    except Exception:
        return _json_error("Forbidden", status=403)
    event = get_event_for_access(request, alias, event_id, write=True)
    if not event:
        return _json_error("Forbidden", status=403)
    actor = getattr(request.user, "username", None) or getattr(request.user, "email", None) or "unknown"
    payload = dict(event.payload or {})
    payload["voided_at"] = timezone.now().isoformat()
    payload["voided_by"] = actor
    event.status = "void"
    event.payload = payload
    try:
        event.save(using=alias, update_fields=["status", "payload", "updated_at"])
    except Exception:
        logger.exception("event void failed")
        return _json_error("Failed to delete event", status=500)
    return JsonResponse({"success": True, "event_id": str(event.id), "status": "void"})
