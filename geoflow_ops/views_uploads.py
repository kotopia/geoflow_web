"""Tenant attachment upload/download API."""
from __future__ import annotations

import json
import logging
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, connections, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from .models import Attachment, ProcessEvent, ProcessEventAttachment
from .services.entity_access import (
    authorize_attachment_read,
    authorize_attachment_write,
    require_tenant_context,
)
from .services.s3_service import (
    S3ObjectVerificationError,
    build_object_key,
    extract_extension,
    generate_presigned_get_url,
    generate_presigned_put_url,
    head_private_object,
)

logger = logging.getLogger(__name__)

DIRECT_UPLOAD_PURPOSES = {
    ("employee", "photo"),
    ("employee", "photo_thumb"),
    ("employee", "doc"),
    ("partner", "doc"),
    ("event", "doc"),
    ("orgunit", "business_registration"),
    ("orgunit", "certification_evaluation"),
}
IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
PDF_EXTENSIONS = {"pdf"}
PDF_MIME_TYPES = {"application/pdf"}
ENTITY_FOLDERS = {
    "employee": "employees",
    "partner": "partners",
    "event": "events",
    "orgunit": "orgunits",
}


def _document_title(data, entity_type):
    if entity_type != "orgunit":
        return "", None
    title = str(data.get("document_title") or "").strip()
    if not title:
        return "", "document_title is required"
    if len(title) > 200:
        return "", "document_title is too long"
    return title, None


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


def _normalize_mime(value) -> str:
    return str(value or "").split(";", 1)[0].strip().lower()


def _parse_size(value):
    if value in (None, ""):
        return None
    try:
        size = int(value)
    except (TypeError, ValueError):
        return None
    return size if size >= 0 else None


def _validate_upload_combination(entity_type, purpose, filename, mime_type, size_bytes):
    if (entity_type, purpose) not in DIRECT_UPLOAD_PURPOSES:
        return "Unsupported upload target"
    if not filename or len(str(filename)) > 512:
        return "Invalid filename"
    if size_bytes is None:
        return "size_bytes is required"
    extension = extract_extension(str(filename))
    mime_type = _normalize_mime(mime_type)

    if (entity_type, purpose) == ("employee", "photo"):
        if extension not in IMAGE_EXTENSIONS or mime_type not in IMAGE_MIME_TYPES:
            return "Unsupported employee photo type"
    elif (entity_type, purpose) == ("employee", "photo_thumb"):
        if extension not in {"jpg", "jpeg"} or mime_type != "image/jpeg":
            return "Unsupported employee thumbnail type"
    elif (entity_type, purpose) == ("employee", "doc"):
        if extension not in PDF_EXTENSIONS or mime_type not in PDF_MIME_TYPES:
            return "Unsupported employee document type"
    elif entity_type == "event" and purpose == "doc":
        if not extension or extension == "bin" or not mime_type:
            return "Invalid event document type"
    elif entity_type == "partner" and purpose == "doc":
        if not extension or extension == "bin":
            return "Invalid partner document type"
    elif entity_type == "orgunit":
        if not extension or extension == "bin" or not mime_type:
            return "Invalid company document type"
    return None


def _canonical_event_id(entity_type, entity_id, event_id_value):
    if entity_type != "event":
        return None, None
    event_id = _parse_uuid(event_id_value)
    if event_id is None or event_id != entity_id:
        return None, "event_id must match entity_id"
    return event_id, None


def _validate_parent(alias, entity_type, entity_id, purpose, parent_id):
    if purpose == "photo_thumb":
        if entity_type != "employee" or parent_id is None:
            return "photo_thumb requires an employee photo parent"
        parent = Attachment.objects.using(alias).filter(pk=parent_id).first()
        if (
            not parent
            or parent.entity_type != "employee"
            or parent.entity_id != entity_id
            or parent.purpose != "photo"
            or not parent.active
            or parent.deleted_at is not None
            or parent.is_deleted
        ):
            return "Invalid parent attachment"
        return None
    if parent_id is not None:
        return "parent_attachment_id is not allowed for this purpose"
    return None


def _expected_prefix(alias, entity_type, entity_id, purpose):
    folder = ENTITY_FOLDERS.get(entity_type)
    if not folder:
        return None
    return f"tenants/{alias}/{folder}/{entity_id}/{purpose}/"


def _refresh_avatar_session(request, alias, attachment):
    if attachment.entity_type != "employee" or attachment.purpose not in {
        "photo", "photo_thumb"
    }:
        return
    try:
        user_email = getattr(request.user, "username", "") or getattr(request.user, "email", "")
        with connections[alias].cursor() as cur:
            cur.execute(
                """
                SELECT id::text, name
                  FROM hr.employee_profile
                 WHERE lower(email) = lower(%s)
                 LIMIT 1
                """,
                [user_email],
            )
            row = cur.fetchone()
        if not row or str(row[0]) != str(attachment.entity_id):
            return
        if attachment.purpose == "photo_thumb":
            request.session["avatar_attachment_id"] = str(attachment.id)
            request.session["topbar_avatar_attachment_id"] = str(attachment.id)
        elif not request.session.get("avatar_attachment_id"):
            request.session["avatar_attachment_id"] = str(attachment.id)
            request.session["topbar_avatar_attachment_id"] = str(attachment.id)
        request.session["topbar_name"] = row[1] or user_email
        request.session["topbar_emp_id"] = str(row[0])
    except Exception:
        logger.warning("avatar session refresh failed")


@login_required
@require_POST
def presign_put(request):
    try:
        alias = require_tenant_context(request)
    except Exception:
        return _json_error("Forbidden", status=403)

    data = _parse_json(request)
    if data is None:
        return _json_error("Invalid JSON")

    entity_type = str(data.get("entity_type") or "").strip().lower()
    purpose = str(data.get("purpose") or "").strip().lower()
    entity_id = _parse_uuid(data.get("entity_id"))
    filename = str(data.get("filename") or "").strip()
    mime_type = _normalize_mime(data.get("mime_type"))
    size_bytes = _parse_size(data.get("size_bytes"))
    parent_id = _parse_uuid(data.get("parent_attachment_id")) if data.get("parent_attachment_id") else None

    if entity_id is None:
        return _json_error("Invalid entity_id")
    event_id, error = _canonical_event_id(entity_type, entity_id, data.get("event_id"))
    if error:
        return _json_error(error)
    error = _validate_upload_combination(entity_type, purpose, filename, mime_type, size_bytes)
    if error:
        return _json_error(error)
    if not authorize_attachment_write(request, alias, entity_type, entity_id):
        return _json_error("Forbidden", status=403)
    error = _validate_parent(alias, entity_type, entity_id, purpose, parent_id)
    if error:
        return _json_error(error)

    try:
        object_key = build_object_key(
            tenant_db_alias=alias,
            entity_type=entity_type,
            entity_id=str(entity_id),
            purpose=purpose,
            extension=extract_extension(filename),
            event_id=str(event_id) if event_id else None,
        )
        presigned = generate_presigned_put_url(
            object_key=object_key,
            mime_type=mime_type,
            expires_in=3600,
        )
    except Exception:
        logger.exception("presign put failed")
        return _json_error("Failed to generate upload URL", status=500)

    return JsonResponse(
        {
            "object_key": object_key,
            "presigned_url": presigned["presigned_url"],
            "headers": presigned.get("headers", {}),
        }
    )


@login_required
@require_POST
def commit(request):
    try:
        alias = require_tenant_context(request)
    except Exception:
        return _json_error("Forbidden", status=403)

    data = _parse_json(request)
    if data is None:
        return _json_error("Invalid JSON")

    object_key = str(data.get("object_key") or "")
    entity_type = str(data.get("entity_type") or "").strip().lower()
    purpose = str(data.get("purpose") or "").strip().lower()
    entity_id = _parse_uuid(data.get("entity_id"))
    original_name = str(data.get("original_name") or "").strip()
    mime_type = _normalize_mime(data.get("mime_type"))
    declared_size = _parse_size(data.get("size_bytes"))
    parent_id = _parse_uuid(data.get("parent_attachment_id")) if data.get("parent_attachment_id") else None
    kind = str(data.get("kind") or "file")[:50]
    document_title, title_error = _document_title(data, entity_type)

    if not object_key or entity_id is None or not original_name:
        return _json_error("Missing or invalid upload metadata")
    if title_error:
        return _json_error(title_error)
    event_id, error = _canonical_event_id(entity_type, entity_id, data.get("event_id"))
    if error:
        return _json_error(error)
    error = _validate_upload_combination(entity_type, purpose, original_name, mime_type, declared_size)
    if error:
        return _json_error(error)
    if not authorize_attachment_write(request, alias, entity_type, entity_id):
        return _json_error("Forbidden", status=403)
    error = _validate_parent(alias, entity_type, entity_id, purpose, parent_id)
    if error:
        return _json_error(error)

    prefix = _expected_prefix(alias, entity_type, entity_id, purpose)
    if not prefix or not object_key.startswith(prefix):
        return _json_error("Invalid object key")

    try:
        metadata = head_private_object(object_key)
    except S3ObjectVerificationError:
        logger.warning("upload commit object verification failed")
        return _json_error("Uploaded object could not be verified", status=400)
    except Exception:
        logger.exception("upload commit object verification error")
        return _json_error("Uploaded object could not be verified", status=500)

    if metadata.size_bytes != declared_size:
        return _json_error("Uploaded object size mismatch")
    if mime_type and metadata.content_type != mime_type:
        return _json_error("Uploaded object type mismatch")
    if not metadata.encryption_matches:
        return _json_error("Uploaded object encryption mismatch")

    try:
        with transaction.atomic(using=alias):
            attachment = Attachment(
                entity_type=entity_type,
                entity_id=entity_id,
                purpose=purpose,
                object_key=object_key,
                original_name=original_name,
                mime_type=metadata.content_type,
                size_bytes=metadata.size_bytes,
                sha256=None,
                kind=kind,
                parent_id=parent_id,
                active=True,
                ord=0,
                meta={"document_title": document_title} if document_title else {},
            )
            attachment.save(using=alias)

            event_link_id = None
            if entity_type == "event":
                event = ProcessEvent.objects.using(alias).select_for_update().get(pk=event_id)
                link, _ = ProcessEventAttachment.objects.using(alias).get_or_create(
                    event=event,
                    attachment=attachment,
                    defaults={"role": "primary", "ord": 0},
                )
                event_link_id = str(link.id)
                if event.status == "draft":
                    event.status = "done"
                    event.save(using=alias, update_fields=["status", "updated_at"])
    except IntegrityError:
        logger.warning("duplicate or conflicting upload commit")
        return _json_error("Attachment already committed", status=409)
    except Exception:
        logger.exception("upload commit failed")
        return _json_error("Failed to commit attachment", status=500)

    _refresh_avatar_session(request, alias, attachment)
    response = {"attachment_id": str(attachment.id), "object_key": object_key}
    if event_link_id:
        response["event_link_id"] = event_link_id
    return JsonResponse(response)


@login_required
@require_GET
def presign_get(request, attachment_id):
    try:
        alias = require_tenant_context(request)
    except Exception:
        return _json_error("Forbidden", status=403)

    att = Attachment.objects.using(alias).filter(pk=attachment_id).first()
    if not att:
        return _json_error("Attachment not found", status=404)
    if att.deleted_at or att.is_deleted or not att.active:
        return _json_error("Attachment has been deleted", status=410)
    if not authorize_attachment_read(request, alias, att):
        return _json_error("Forbidden", status=403)

    mode = str(request.GET.get("mode") or "inline").strip().lower()
    if mode not in {"inline", "download"}:
        return _json_error("Invalid mode")
    disposition = "attachment" if mode == "download" else "inline"

    try:
        url = generate_presigned_get_url(
            att.object_key,
            expires_in=3600,
            content_type=att.mime_type or None,
            disposition=disposition,
            filename=att.original_name,
        )
    except Exception:
        logger.exception("presign get failed")
        return _json_error("Failed to generate download URL", status=500)
    return JsonResponse(
        {
            "presigned_url": url,
            "original_name": att.original_name,
            "mime_type": att.mime_type or "",
        }
    )


@login_required
@require_http_methods(["DELETE"])
def delete_attachment(request, attachment_id):
    try:
        alias = require_tenant_context(request)
    except Exception:
        return _json_error("Forbidden", status=403)

    att = Attachment.objects.using(alias).filter(pk=attachment_id).first()
    if not att:
        return _json_error("Attachment not found", status=404)
    if att.deleted_at or att.is_deleted:
        return _json_error("Already deleted", status=410)
    if not authorize_attachment_write(request, alias, att.entity_type, att.entity_id):
        return _json_error("Forbidden", status=403)

    att.deleted_at = timezone.now()
    att.deleted_by = getattr(request.user, "username", "") or getattr(request.user, "email", "")
    att.is_deleted = True
    att.active = False
    att.save(using=alias, update_fields=["deleted_at", "deleted_by", "is_deleted", "active", "updated_at"])

    if str(att.id) == request.session.get("avatar_attachment_id"):
        request.session["avatar_attachment_id"] = None
        request.session["topbar_avatar_attachment_id"] = None
    return JsonResponse({"success": True})
