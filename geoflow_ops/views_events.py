"""Tenant process-event JSON API."""
from __future__ import annotations

import json
import logging
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET, require_POST

from .models import ProcessEvent, ProcessEventAttachment
from .services.entity_access import (
    authorize_scope_read,
    authorize_scope_write,
    get_event_for_access,
    has_scope_permission,
    require_tenant_context,
)

logger = logging.getLogger(__name__)

ALLOWED_SCOPE_TYPES = {"contract", "employee", "orgunit"}
ALLOWED_STATUSES = {"draft", "open", "done", "void"}
MAX_TITLE_LENGTH = ProcessEvent._meta.get_field("title").max_length or 255
MAX_STAGE_LENGTH = ProcessEvent._meta.get_field("stage").max_length or 50
MAX_EVENT_TYPE_LENGTH = ProcessEvent._meta.get_field("event_type").max_length or 50
MAX_MEMO_LENGTH = 10000


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


def _validate_mutable_fields(data, *, creating: bool):
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

    if creating and (not cleaned.get("stage") or not cleaned.get("event_type")):
        return None, "stage and event_type are required"

    if creating or "status" in data:
        status = str(data.get("status") or "draft")
        if status not in ALLOWED_STATUSES:
            return None, "Invalid status"
        cleaned["status"] = status

    for name in ("occurred_at", "due_at"):
        if creating or name in data:
            value, error = _clean_date(data.get(name), name)
            if error:
                return None, error
            cleaned[name] = value

    return cleaned, None


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

    cleaned, error = _validate_mutable_fields(data, creating=True)
    if error:
        return _json_error(error)

    user_name = (
        getattr(request.user, "username", None)
        or getattr(request.user, "email", None)
        or "unknown"
    )
    try:
        event = ProcessEvent.objects.using(alias).create(
            scope_type=scope_type,
            scope_id=scope_id,
            created_by=user_name,
            **cleaned,
        )
    except Exception:
        logger.exception("event create failed")
        return _json_error("Failed to create event", status=500)

    payload = {
        "id": str(event.id),
        "status": event.status,
        "scope_type": event.scope_type,
        "scope_id": str(event.scope_id),
        "stage": event.stage,
        "event_type": event.event_type,
        "title": event.title,
    }
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
        events = list(
            ProcessEvent.objects.using(alias)
            .filter(scope_type=scope_type, scope_id=scope_id)
            .order_by("stage", "occurred_at", "created_at")
        )
        result = []
        for event in events:
            links = (
                ProcessEventAttachment.objects.using(alias)
                .filter(event=event)
                .select_related("attachment")
                .order_by("ord", "created_at")
            )
            attachments = []
            for link in links:
                att = link.attachment
                if att.deleted_at:
                    continue
                attachments.append(
                    {
                        "id": str(att.id),
                        "original_name": att.original_name,
                        "mime_type": att.mime_type or "",
                        "size_bytes": att.size_bytes,
                        "role": link.role,
                    }
                )
            result.append(
                {
                    "id": str(event.id),
                    "scope_type": event.scope_type,
                    "scope_id": str(event.scope_id),
                    "stage": event.stage,
                    "event_type": event.event_type,
                    "title": event.title,
                    "memo": event.memo,
                    "status": event.status,
                    "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
                    "due_at": event.due_at.isoformat() if event.due_at else None,
                    "created_at": event.created_at.isoformat(),
                    "updated_at": event.updated_at.isoformat() if event.updated_at else None,
                    "created_by": event.created_by,
                    "attachment_count": len(attachments),
                    "attachments": attachments,
                }
            )
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
    cleaned, error = _validate_mutable_fields(data, creating=False)
    if error:
        return _json_error(error)

    for key, value in cleaned.items():
        setattr(event, key, value)
    try:
        event.save(using=alias)
    except Exception:
        logger.exception("event update failed")
        return _json_error("Failed to update event", status=500)
    return JsonResponse({"success": True, "event_id": str(event.id)})


@login_required
@require_POST
def delete_event(request, event_id):
    try:
        alias = require_tenant_context(request)
    except Exception:
        return _json_error("Forbidden", status=403)

    event = get_event_for_access(request, alias, event_id, write=True)
    if not event:
        return _json_error("Forbidden", status=403)

    try:
        with transaction.atomic(using=alias):
            ProcessEventAttachment.objects.using(alias).filter(event=event).delete()
            event.delete(using=alias)
    except Exception:
        logger.exception("event delete failed")
        return _json_error("Failed to delete event", status=500)
    return JsonResponse({"success": True})
