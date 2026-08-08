from __future__ import annotations

import json

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from . import views_uploads
from .services.entity_access import require_tenant_context

UPLOAD_LIMITS = {
    ("employee", "photo"): ("GEOFLOW_UPLOAD_EMPLOYEE_PHOTO_MAX_BYTES", 15 * 1024 * 1024),
    ("employee", "photo_thumb"): ("GEOFLOW_UPLOAD_EMPLOYEE_THUMB_MAX_BYTES", 2 * 1024 * 1024),
    ("employee", "doc"): ("GEOFLOW_UPLOAD_EMPLOYEE_DOC_MAX_BYTES", 25 * 1024 * 1024),
    ("event", "doc"): ("GEOFLOW_UPLOAD_EVENT_DOC_MAX_BYTES", 100 * 1024 * 1024),
}


def _json_error(message: str, status: int) -> JsonResponse:
    return JsonResponse({"error": message}, status=status)


def _payload(request):
    try:
        data = json.loads(request.body or b"{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


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


def _enforce_size(request):
    require_tenant_context(request)
    data = _payload(request)
    if data is None:
        return None
    entity_type = str(data.get("entity_type") or "").strip().lower()
    purpose = str(data.get("purpose") or "").strip().lower()
    limit = _configured_limit(entity_type, purpose)
    if limit is None:
        return None
    try:
        size_bytes = int(data.get("size_bytes"))
    except (TypeError, ValueError):
        return None
    if size_bytes > limit:
        return _json_error("Upload exceeds the configured size limit", status=413)
    return None


@login_required
@require_POST
def presign_put(request):
    blocked = _enforce_size(request)
    if blocked:
        return blocked
    return views_uploads.presign_put(request)


@login_required
@require_POST
def commit(request):
    blocked = _enforce_size(request)
    if blocked:
        return blocked
    return views_uploads.commit(request)
