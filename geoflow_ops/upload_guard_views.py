from __future__ import annotations

import json
import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from . import views_uploads
from .models import Attachment
from .services.entity_access import authorize_attachment_read, require_tenant_context
from .services.s3_service import extract_extension, generate_presigned_get_url

logger = logging.getLogger(__name__)

UPLOAD_LIMITS = {
    ("employee", "photo"): ("GEOFLOW_UPLOAD_EMPLOYEE_PHOTO_MAX_BYTES", 15 * 1024 * 1024),
    ("employee", "photo_thumb"): ("GEOFLOW_UPLOAD_EMPLOYEE_THUMB_MAX_BYTES", 2 * 1024 * 1024),
    ("employee", "doc"): ("GEOFLOW_UPLOAD_EMPLOYEE_DOC_MAX_BYTES", 25 * 1024 * 1024),
    ("partner", "doc"): ("GEOFLOW_UPLOAD_PARTNER_DOC_MAX_BYTES", 25 * 1024 * 1024),
    ("event", "doc"): ("GEOFLOW_UPLOAD_EVENT_DOC_MAX_BYTES", 100 * 1024 * 1024),
}

BLOCKED_ACTIVE_DOC_EXTENSIONS = {
    "html", "htm", "xhtml", "svg", "js", "mjs", "xml",
}
BLOCKED_ACTIVE_DOC_MIME_TYPES = {
    "text/html", "application/xhtml+xml", "image/svg+xml", "application/javascript",
    "text/javascript", "application/ecmascript", "text/ecmascript", "application/xml", "text/xml",
}
INLINE_SAFE_MIME_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/webp", "text/plain"}
LEGACY_GENERIC_MIME_TYPES = {
    "", "application/octet-stream", "binary/octet-stream", "application/force-download", "application/download",
}
LEGACY_INLINE_EXTENSION_MIME_TYPES = {
    "pdf": "application/pdf",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "txt": "text/plain",
}
LEGACY_INLINE_MIME_ALIASES = {
    "application/x-pdf": "application/pdf",
    "image/jpg": "image/jpeg",
}


def _json_error(message: str, status: int) -> JsonResponse:
    return JsonResponse({"error": message}, status=status)


def _payload(request):
    try:
        data = json.loads(request.body or b"{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _normalize_mime(value) -> str:
    return str(value or "").split(";", 1)[0].strip().lower()


def _effective_inline_mime(attachment) -> str:
    """Return a safe inline MIME, including conservative legacy metadata fallback."""
    stored_mime = _normalize_mime(getattr(attachment, "mime_type", None))
    stored_mime = LEGACY_INLINE_MIME_ALIASES.get(stored_mime, stored_mime)
    if stored_mime in INLINE_SAFE_MIME_TYPES:
        return stored_mime
    if stored_mime not in LEGACY_GENERIC_MIME_TYPES:
        return ""

    filename = str(getattr(attachment, "original_name", "") or "")
    extension = extract_extension(filename)
    if not extension:
        extension = extract_extension(str(getattr(attachment, "object_key", "") or ""))
    return LEGACY_INLINE_EXTENSION_MIME_TYPES.get(extension, "")


def _configured_limit(entity_type: str, purpose: str) -> int | None:
    item = UPLOAD_LIMITS.get((entity_type, purpose))
    if not item:
        return None
    setting_name, default = item
    try:
        value = int(getattr(settings, setting_name, default))
    except (TypeError, ValueError):
        value = default
    return max(1, value)


def _guard_upload_payload(request):
    require_tenant_context(request)
    data = _payload(request)
    if data is None:
        return None
    entity_type = str(data.get("entity_type") or "").strip().lower()
    purpose = str(data.get("purpose") or "").strip().lower()
    limit = _configured_limit(entity_type, purpose)
    if limit is not None:
        try:
            size_bytes = int(data.get("size_bytes"))
        except (TypeError, ValueError):
            size_bytes = None
        if size_bytes is not None and size_bytes > limit:
            return _json_error("Upload exceeds the configured size limit", status=413)
    if entity_type in {"partner", "event"} and purpose == "doc":
        filename = data.get("filename") or data.get("original_name") or ""
        extension = extract_extension(str(filename))
        mime_type = _normalize_mime(data.get("mime_type"))
        if extension in BLOCKED_ACTIVE_DOC_EXTENSIONS or mime_type in BLOCKED_ACTIVE_DOC_MIME_TYPES:
            return _json_error("Active document type is not allowed", status=415)
    return None


def _attachment_for_read(request, attachment_id):
    try:
        alias = require_tenant_context(request)
    except Exception:
        return None, None, _json_error("Forbidden", status=403)
    attachment = Attachment.objects.using(alias).filter(pk=attachment_id).first()
    if not attachment:
        return alias, None, _json_error("Attachment not found", status=404)
    if attachment.deleted_at or attachment.is_deleted or not attachment.active:
        return alias, None, _json_error("Attachment has been deleted", status=410)
    if not authorize_attachment_read(request, alias, attachment):
        return alias, None, _json_error("Forbidden", status=403)
    return alias, attachment, None


@login_required
@require_POST
def presign_put(request):
    try:
        blocked = _guard_upload_payload(request)
    except Exception:
        return _json_error("Forbidden", status=403)
    if blocked:
        return blocked
    return views_uploads.presign_put(request)


@login_required
@require_POST
def commit(request):
    try:
        blocked = _guard_upload_payload(request)
    except Exception:
        return _json_error("Forbidden", status=403)
    if blocked:
        return blocked
    return views_uploads.commit(request)


@never_cache
@login_required
@require_GET
def presign_get(request, attachment_id):
    try:
        alias = require_tenant_context(request)
    except Exception:
        return _json_error("Forbidden", status=403)
    attachment = Attachment.objects.using(alias).filter(pk=attachment_id).first()
    if not attachment:
        return _json_error("Attachment not found", status=404)
    if attachment.deleted_at or attachment.is_deleted or not attachment.active:
        return _json_error("Attachment has been deleted", status=410)
    if not authorize_attachment_read(request, alias, attachment):
        return _json_error("Forbidden", status=403)

    mode = str(request.GET.get("mode") or "inline").strip().lower()
    if mode not in {"inline", "download"}:
        return _json_error("Invalid mode", status=400)
    stored_mime = _normalize_mime(attachment.mime_type)
    inline_mime = _effective_inline_mime(attachment)
    inline_allowed = mode == "inline" and bool(inline_mime)
    disposition = "inline" if inline_allowed else "attachment"
    response_type = inline_mime if inline_allowed else "application/octet-stream"
    try:
        url = generate_presigned_get_url(
            attachment.object_key,
            expires_in=3600,
            content_type=response_type,
            disposition=disposition,
            filename=attachment.original_name,
        )
    except Exception:
        logger.exception("guarded presign get failed")
        return _json_error("Failed to generate download URL", status=500)
    return JsonResponse({
        "presigned_url": url,
        "original_name": attachment.original_name,
        "mime_type": inline_mime or stored_mime,
        "effective_mode": "inline" if inline_allowed else "download",
    })


@never_cache
@login_required
@require_GET
def preview(request, attachment_id):
    """Authenticated HTML preview shell distinct from download navigation."""
    _, attachment, error = _attachment_for_read(request, attachment_id)
    if error:
        return error
    mime_type = _effective_inline_mime(attachment)
    if not mime_type:
        return _json_error("Preview is not supported for this file type", status=415)
    try:
        preview_url = generate_presigned_get_url(
            attachment.object_key,
            expires_in=3600,
            content_type=mime_type,
            disposition="inline",
            filename=attachment.original_name,
        )
    except Exception:
        logger.exception("guarded preview presign failed")
        return _json_error("Failed to generate preview URL", status=500)
    return render(request, "geoflow_ops/attachments/preview.html", {
        "attachment": attachment,
        "preview_url": preview_url,
        "mime_type": mime_type,
    })
