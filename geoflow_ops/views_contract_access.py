from __future__ import annotations

from uuid import UUID

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import connections, transaction
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from .services.contract_access import can_approve_contract_document_access
from .services.employee_access import current_employee_id
from .services.entity_access import require_tenant_context


@login_required
@require_POST
def request_contract_document_access(request, contract_id: UUID):
    alias = require_tenant_context(request)
    employee_id = current_employee_id(alias, request)
    if not employee_id:
        raise PermissionDenied("Employee profile required")
    reason = str(request.POST.get("reason") or "").strip()[:1000]
    with transaction.atomic(using=alias):
        with connections[alias].cursor() as cur:
            cur.execute(
                """
                INSERT INTO ops.contract_document_access_requests
                    (contract_id, requester_employee_id, reason, status, requested_at)
                SELECT %s, %s, %s, 'pending', now()
                 WHERE NOT EXISTS (
                    SELECT 1 FROM ops.contract_document_access_requests
                     WHERE contract_id=%s AND requester_employee_id=%s AND status='pending'
                 )
                """,
                [str(contract_id), str(employee_id), reason or None, str(contract_id), str(employee_id)],
            )
    messages.success(request, "계약 문서 열람을 요청했습니다.")
    return redirect("tenant:contract_detail", pk=contract_id)


@login_required
@require_POST
def decide_contract_document_access(request, request_id: UUID):
    alias = require_tenant_context(request)
    if not can_approve_contract_document_access(request):
        raise PermissionDenied("Permission denied")
    decision = str(request.POST.get("decision") or "").strip().lower()
    if decision not in {"approved", "rejected"}:
        raise PermissionDenied("Invalid decision")
    reviewer = current_employee_id(alias, request)
    with transaction.atomic(using=alias):
        with connections[alias].cursor() as cur:
            cur.execute(
                """
                UPDATE ops.contract_document_access_requests
                   SET status=%s,
                       reviewed_by_employee_id=%s,
                       reviewed_at=now()
                 WHERE id=%s AND status='pending'
                RETURNING contract_id::text
                """,
                [decision, str(reviewer) if reviewer else None, str(request_id)],
            )
            row = cur.fetchone()
    if not row:
        raise PermissionDenied("Request not found")
    messages.success(request, "계약 문서 열람 요청을 처리했습니다.")
    return redirect("tenant:contract_detail", pk=row[0])
