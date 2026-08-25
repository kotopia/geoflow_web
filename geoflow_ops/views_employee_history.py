from __future__ import annotations

import json
import re
from uuid import UUID

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, connections, transaction
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .models import Attachment
from .services.employee_access import employee_access_policy
from .services.entity_access import require_tenant_context
from .services.s3_service import (
    S3ObjectVerificationError,
    build_object_key,
    extract_extension,
    generate_presigned_put_url,
    head_private_object,
)
from .views_employee_profile import HISTORY_SECTIONS
from .views_employees import _parse_iso_date


HISTORY_TABLES = {
    "education": "hr.employee_education",
    "qualification": "hr.employee_qualification",
    "technical_grade": "hr.employee_technical_grade",
    "career": "hr.employee_career",
}
HISTORY_DOCUMENT_PURPOSE = "history_doc"
HISTORY_DOCUMENT_KIND_PREFIX = "employee_history"
HISTORY_DOCUMENT_MIME_BY_EXTENSION = {
    "pdf": {"application/pdf"},
    "jpg": {"image/jpeg", "image/jpg"},
    "jpeg": {"image/jpeg", "image/jpg"},
    "png": {"image/png"},
    "webp": {"image/webp"},
    "txt": {"text/plain"},
}


def _json_error(message: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"error": message}, status=status)


def _parse_json(request):
    try:
        value = json.loads(request.body or b"{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _normalize_mime(value) -> str:
    return str(value or "").split(";", 1)[0].strip().lower()


def _optional_post(request, name: str):
    value = str(request.POST.get(name) or "").strip()
    return value or None


def _authorize_employee_edit(request, emp_id) -> str:
    alias = require_tenant_context(request)
    policy = employee_access_policy(request, alias)
    if not policy.can_edit(emp_id):
        raise PermissionDenied("Permission denied")
    return alias


def _uuid(value):
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _history_record_exists(alias: str, emp_id, section: str, record_id) -> bool:
    table = HISTORY_TABLES.get(section)
    record_uuid = _uuid(record_id)
    if not table or record_uuid is None:
        return False
    with connections[alias].cursor() as cur:
        cur.execute(
            f"SELECT 1 FROM {table} WHERE id=%s AND employee_id=%s AND active=true LIMIT 1",
            [str(record_uuid), str(emp_id)],
        )
        return cur.fetchone() is not None


def _history_kind(section: str, record_id) -> str:
    if section not in HISTORY_TABLES or _uuid(record_id) is None:
        raise ValueError("Invalid history document target")
    return f"{HISTORY_DOCUMENT_KIND_PREFIX}:{section}:{record_id}"


def _history_object_prefix(alias: str, emp_id) -> str:
    return f"tenants/{alias}/employees/{emp_id}/{HISTORY_DOCUMENT_PURPOSE}/"


def _validate_document(filename: str, mime_type: str, size_bytes) -> str | None:
    if not filename or len(filename) > 512:
        return "Invalid filename"
    try:
        size = int(size_bytes)
    except (TypeError, ValueError):
        return "size_bytes is required"
    if size < 0:
        return "Invalid file size"
    default_limit = 25 * 1024 * 1024
    try:
        limit = int(getattr(settings, "GEOFLOW_UPLOAD_EMPLOYEE_HISTORY_DOC_MAX_BYTES", default_limit))
    except (TypeError, ValueError):
        limit = default_limit
    if size > max(1, limit):
        return "Upload exceeds the configured size limit"

    extension = extract_extension(filename)
    allowed_mimes = HISTORY_DOCUMENT_MIME_BY_EXTENSION.get(extension)
    normalized_mime = _normalize_mime(mime_type)
    if not allowed_mimes or normalized_mime not in allowed_mimes:
        return "Unsupported employee history document type"
    return None


@require_POST
def history_save(request, emp_id):
    alias = _authorize_employee_edit(request, emp_id)
    section = str(request.POST.get("section") or "").strip().lower()
    config = HISTORY_SECTIONS.get(section)
    if not config or section not in HISTORY_TABLES:
        return _json_error("지원하지 않는 직원 이력 구분입니다.")

    required_value = _optional_post(request, config["required"])
    if not required_value:
        return _json_error("필수 항목을 입력하세요.")

    record_id = str(request.POST.get("record_id") or "").strip() or None
    columns: list[str] = []
    values: list[object] = []
    assignments: list[str] = []
    for field, field_type in config["fields"]:
        columns.append(field)
        value = _optional_post(request, field)
        if field_type == "date" and value:
            parsed = _parse_iso_date(value)
            value = parsed.isoformat() if parsed else None
        values.append(value)
        assignments.append(f"{field}=%s" + ("::date" if field_type == "date" else ""))

    table = HISTORY_TABLES[section]
    with transaction.atomic(using=alias):
        with connections[alias].cursor() as cur:
            if record_id:
                if not _history_record_exists(alias, emp_id, section, record_id):
                    return _json_error("직원 이력 항목을 찾을 수 없습니다.", status=404)
                cur.execute(
                    f"UPDATE {table} SET {', '.join(assignments)}, active=true, updated_at=now() "
                    "WHERE id=%s AND employee_id=%s RETURNING id::text",
                    [*values, record_id, str(emp_id)],
                )
                row = cur.fetchone()
                if not row:
                    return _json_error("직원 이력 항목을 저장할 수 없습니다.", status=409)
                saved_id = row[0]
            else:
                placeholders = [
                    "%s::date" if field_type == "date" else "%s"
                    for _, field_type in config["fields"]
                ]
                cur.execute(
                    f"INSERT INTO {table} (employee_id, {', '.join(columns)}) "
                    f"VALUES (%s, {', '.join(placeholders)}) RETURNING id::text",
                    [str(emp_id), *values],
                )
                saved_id = cur.fetchone()[0]

    return JsonResponse({"success": True, "section": section, "record_id": saved_id})


@require_POST
def history_attachment_presign(request, emp_id, section, record_id):
    alias = _authorize_employee_edit(request, emp_id)
    section = str(section or "").strip().lower()
    if not _history_record_exists(alias, emp_id, section, record_id):
        return _json_error("직원 이력 항목을 찾을 수 없습니다.", status=404)

    data = _parse_json(request)
    if data is None:
        return _json_error("Invalid JSON")
    filename = str(data.get("filename") or "").strip()
    mime_type = _normalize_mime(data.get("mime_type"))
    size_bytes = data.get("size_bytes")
    error = _validate_document(filename, mime_type, size_bytes)
    if error:
        return _json_error(error, status=413 if "size limit" in error else 415)

    try:
        object_key = build_object_key(
            tenant_db_alias=alias,
            entity_type="employee",
            entity_id=str(emp_id),
            purpose=HISTORY_DOCUMENT_PURPOSE,
            extension=extract_extension(filename),
        )
        presigned = generate_presigned_put_url(
            object_key=object_key,
            mime_type=mime_type,
            expires_in=3600,
        )
    except Exception:
        return _json_error("Failed to generate upload URL", status=500)

    return JsonResponse({
        "object_key": object_key,
        "presigned_url": presigned["presigned_url"],
        "headers": presigned.get("headers", {}),
    })


@require_POST
def history_attachment_commit(request, emp_id, section, record_id):
    alias = _authorize_employee_edit(request, emp_id)
    section = str(section or "").strip().lower()
    if not _history_record_exists(alias, emp_id, section, record_id):
        return _json_error("직원 이력 항목을 찾을 수 없습니다.", status=404)

    data = _parse_json(request)
    if data is None:
        return _json_error("Invalid JSON")

    object_key = str(data.get("object_key") or "").strip()
    filename = str(data.get("original_name") or "").strip()
    mime_type = _normalize_mime(data.get("mime_type"))
    size_bytes = data.get("size_bytes")
    error = _validate_document(filename, mime_type, size_bytes)
    if error:
        return _json_error(error, status=413 if "size limit" in error else 415)
    if not object_key.startswith(_history_object_prefix(alias, emp_id)):
        return _json_error("Invalid object key")

    try:
        metadata = head_private_object(object_key)
    except S3ObjectVerificationError:
        return _json_error("Uploaded object could not be verified", status=400)
    except Exception:
        return _json_error("Uploaded object could not be verified", status=500)

    declared_size = int(size_bytes)
    if metadata.size_bytes != declared_size:
        return _json_error("Uploaded object size mismatch")
    if mime_type and metadata.content_type != mime_type:
        return _json_error("Uploaded object type mismatch")
    if not metadata.encryption_matches:
        return _json_error("Uploaded object encryption mismatch")

    try:
        with transaction.atomic(using=alias):
            attachment = Attachment(
                entity_type="employee",
                entity_id=emp_id,
                purpose=HISTORY_DOCUMENT_PURPOSE,
                object_key=object_key,
                original_name=filename,
                mime_type=metadata.content_type,
                size_bytes=metadata.size_bytes,
                sha256=None,
                kind=_history_kind(section, record_id),
                parent_id=None,
                active=True,
                ord=0,
                meta={"history_section": section, "history_record_id": str(record_id)},
            )
            attachment.save(using=alias)
    except IntegrityError:
        return _json_error("Attachment already committed", status=409)
    except Exception:
        return _json_error("Failed to commit attachment", status=500)

    return JsonResponse({"attachment_id": str(attachment.id), "object_key": object_key})
