from __future__ import annotations

import json
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import connections, transaction
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from control.gf_authz.permissions import gf_has_perm
from .models import Attachment
from .services.entity_access import require_tenant_context
from .services.s3_service import (
    S3ObjectVerificationError,
    build_object_key,
    extract_extension,
    generate_presigned_get_url,
    generate_presigned_put_url,
    head_private_object,
)

MAX_BYTES = 25 * 1024 * 1024
ALLOWED_RECORDS = {
    "invoice": ("fin.tax_invoices", "attachment_id", "finance_invoice"),
    "transaction": ("fin.transactions", "evidence_attachment_id", "finance_evidence"),
}
BLOCKED_EXTENSIONS = {"html", "htm", "xhtml", "svg", "js", "mjs"}


def _json(request):
    try:
        value = json.loads(request.body or b"{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _uuid(value):
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _require_finance(request, *, write=False):
    alias = require_tenant_context(request)
    if write:
        allowed = gf_has_perm(request, "contracts.edit") or gf_has_perm(request, "contracts.create")
    else:
        allowed = gf_has_perm(request, "contracts.view")
    if not allowed:
        raise PermissionDenied("Permission denied")
    return alias


def _record(alias, record_type, record_id):
    config = ALLOWED_RECORDS.get(record_type)
    if not config or not record_id:
        return None
    table, attachment_column, purpose = config
    with connections[alias].cursor() as cur:
        cur.execute(
            f"SELECT contract_id::text, my_org_unit_id::text, {attachment_column}::text FROM {table} WHERE id=%s AND is_deleted=false LIMIT 1",
            [str(record_id)],
        )
        row = cur.fetchone()
    if not row:
        return None
    contract_id, org_unit_id, attachment_id = row
    if contract_id:
        entity_type, entity_id = "contract", contract_id
    elif org_unit_id:
        entity_type, entity_id = "orgunit", org_unit_id
    else:
        return None
    return {
        "table": table,
        "column": attachment_column,
        "purpose": purpose,
        "contract_id": contract_id,
        "org_unit_id": org_unit_id,
        "attachment_id": attachment_id,
        "entity_type": entity_type,
        "entity_id": entity_id,
    }


@login_required
@require_POST
def finance_attachment_presign(request):
    alias = _require_finance(request, write=True)
    data = _json(request)
    record_type = str(data.get("record_type") or "").strip().lower()
    record_id = _uuid(data.get("record_id"))
    record = _record(alias, record_type, record_id)
    if not record:
        return JsonResponse({"error": "증빙 첨부를 위해 귀속회사 또는 계약 연결이 필요합니다."}, status=400)
    filename = str(data.get("filename") or "").strip()
    mime_type = str(data.get("mime_type") or "application/octet-stream").split(";", 1)[0].strip().lower()
    try:
        size_bytes = int(data.get("size_bytes") or 0)
    except (TypeError, ValueError):
        size_bytes = 0
    extension = extract_extension(filename)
    if not filename or size_bytes < 1 or size_bytes > MAX_BYTES or extension in BLOCKED_EXTENSIONS or extension == "bin":
        return JsonResponse({"error": "파일 형식 또는 크기를 확인하세요. 최대 25MB입니다."}, status=400)
    object_key = build_object_key(alias, record["entity_type"], record["entity_id"], record["purpose"], extension)
    presigned = generate_presigned_put_url(object_key, mime_type=mime_type, expires_in=900)
    return JsonResponse({"object_key": object_key, **presigned})


@login_required
@require_POST
def finance_attachment_commit(request):
    alias = _require_finance(request, write=True)
    data = _json(request)
    record_type = str(data.get("record_type") or "").strip().lower()
    record_id = _uuid(data.get("record_id"))
    record = _record(alias, record_type, record_id)
    if not record:
        return JsonResponse({"error": "Finance 대상을 찾을 수 없습니다."}, status=404)
    object_key = str(data.get("object_key") or "").strip()
    filename = str(data.get("filename") or "").strip()
    folder = "contracts" if record["entity_type"] == "contract" else "orgunits"
    expected_prefix = f"tenants/{alias}/{folder}/{record['entity_id']}/{record['purpose']}/"
    if not object_key.startswith(expected_prefix):
        return JsonResponse({"error": "잘못된 업로드 경로입니다."}, status=400)
    try:
        metadata = head_private_object(object_key)
    except S3ObjectVerificationError:
        return JsonResponse({"error": "업로드 파일을 확인할 수 없습니다."}, status=400)
    if metadata.size_bytes > MAX_BYTES or not metadata.encryption_matches:
        return JsonResponse({"error": "파일 보안 또는 크기 검증에 실패했습니다."}, status=400)

    with transaction.atomic(using=alias):
        attachment = Attachment.objects.using(alias).create(
            entity_type=record["entity_type"],
            entity_id=UUID(record["entity_id"]),
            purpose=record["purpose"],
            object_key=object_key,
            original_name=filename or "finance-document",
            mime_type=metadata.content_type,
            size_bytes=metadata.size_bytes,
            meta={"finance_record_type": record_type, "finance_record_id": str(record_id)},
        )
        with connections[alias].cursor() as cur:
            cur.execute(f"UPDATE {record['table']} SET {record['column']}=%s, updated_at=now() WHERE id=%s AND is_deleted=false", [str(attachment.id), str(record_id)])
    return JsonResponse({"attachment_id": str(attachment.id), "original_name": attachment.original_name})


@login_required
@require_GET
def finance_attachment_download(request, record_type, record_id):
    alias = _require_finance(request, write=False)
    record = _record(alias, str(record_type).lower(), record_id)
    if not record or not record["attachment_id"]:
        return JsonResponse({"error": "첨부파일이 없습니다."}, status=404)
    attachment = Attachment.objects.using(alias).filter(pk=record["attachment_id"], active=True, is_deleted=False).first()
    if not attachment or attachment.deleted_at:
        return JsonResponse({"error": "첨부파일을 찾을 수 없습니다."}, status=404)
    url = generate_presigned_get_url(
        attachment.object_key,
        expires_in=900,
        content_type="application/octet-stream",
        disposition="attachment",
        filename=attachment.original_name,
    )
    return JsonResponse({"presigned_url": url, "original_name": attachment.original_name})
