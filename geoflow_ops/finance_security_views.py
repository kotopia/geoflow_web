from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import connections
from django.http import HttpResponseBadRequest
from django.views.decorators.http import require_GET, require_POST

from control.gf_authz.permissions import gf_has_perm, gf_has_role

from . import views_finance
from .services.entity_access import require_tenant_context


def _require_view(request):
    alias = require_tenant_context(request)
    if not gf_has_perm(request, "contracts.view"):
        raise PermissionDenied("Permission denied")
    return alias


def _require_write(request):
    alias = require_tenant_context(request)
    if not (gf_has_perm(request, "contracts.edit") or gf_has_perm(request, "contracts.create")):
        raise PermissionDenied("Permission denied")
    return alias


def _require_tenant_admin(request):
    alias = _require_write(request)
    if not gf_has_role(request, "tenant_admin"):
        raise PermissionDenied("Tenant administrator permission required")
    return alias


def _code_for_system_key(alias, system_key):
    with connections[alias].cursor() as cur:
        cur.execute(
            "SELECT code FROM ops.settings_nodes WHERE system_key=%s AND active=true LIMIT 1",
            [system_key],
        )
        row = cur.fetchone()
    return row[0] if row else None


def _active_reference_code(alias, field_ref, code):
    if not code:
        return False
    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT 1
              FROM ops.settings_nodes category
              JOIN ops.settings_nodes value ON value.parent_id=category.id
             WHERE category.field_ref=%s
               AND value.code=%s
               AND value.node_type='value'
               AND value.active=true
             LIMIT 1
            """,
            [field_ref, code],
        )
        return bool(cur.fetchone())


def _validate_reference(alias, request, field_ref, post_name):
    code = str(request.POST.get(post_name) or "").strip()
    if code and not _active_reference_code(alias, field_ref, code):
        return HttpResponseBadRequest("환경설정에서 사용할 수 없는 참조값입니다.")
    return None


@login_required
@require_GET
def finance_page(request):
    _require_view(request)
    return views_finance.finance_page(request)


@login_required
@require_POST
def claim_save(request):
    alias = _require_write(request)
    for field_ref, post_name in (
        ("finance.claim_type", "claim_type"),
        ("finance.claim_status", "status"),
    ):
        error = _validate_reference(alias, request, field_ref, post_name)
        if error:
            return error
    return views_finance.claim_save(request)


@login_required
@require_POST
def invoice_save(request):
    alias = _require_write(request)
    for field_ref, post_name in (
        ("finance.invoice_type", "invoice_type"),
        ("finance.invoice_status", "status"),
    ):
        error = _validate_reference(alias, request, field_ref, post_name)
        if error:
            return error

    invoice_type = str(request.POST.get("invoice_type") or "").strip()
    claim_id = str(request.POST.get("claim_id") or "").strip()
    payment_id = str(request.POST.get("payment_request_id") or "").strip()
    sales_code = _code_for_system_key(alias, "finance.value.invoice_type.sales")
    purchase_code = _code_for_system_key(alias, "finance.value.invoice_type.purchase")
    if invoice_type == sales_code and payment_id:
        return HttpResponseBadRequest("매출 세금계산서는 지급건에 연결할 수 없습니다.")
    if invoice_type == purchase_code and claim_id:
        return HttpResponseBadRequest("매입 세금계산서는 청구건에 연결할 수 없습니다.")
    return views_finance.invoice_save(request)


@login_required
@require_POST
def payment_request_save(request):
    alias = _require_write(request)
    for field_ref, post_name in (
        ("finance.payment_status", "status"),
        ("finance.transaction_category", "category_code"),
    ):
        error = _validate_reference(alias, request, field_ref, post_name)
        if error:
            return error
    return views_finance.payment_request_save(request)


@login_required
@require_POST
def transaction_save(request):
    alias = _require_write(request)
    for field_ref, post_name in (
        ("finance.transaction_type", "transaction_type"),
        ("finance.transaction_category", "category_code"),
        ("finance.evidence_type", "evidence_type"),
    ):
        error = _validate_reference(alias, request, field_ref, post_name)
        if error:
            return error

    transaction_type = str(request.POST.get("transaction_type") or "").strip()
    claim_id = str(request.POST.get("claim_id") or "").strip()
    payment_id = str(request.POST.get("payment_request_id") or "").strip()
    incoming_code = _code_for_system_key(alias, "finance.value.transaction_type.in")
    outgoing_code = _code_for_system_key(alias, "finance.value.transaction_type.out")
    if transaction_type == incoming_code and payment_id:
        return HttpResponseBadRequest("입금은 지급건에 연결할 수 없습니다.")
    if transaction_type == outgoing_code and claim_id:
        return HttpResponseBadRequest("출금은 청구건에 연결할 수 없습니다.")
    return views_finance.transaction_save(request)


@login_required
@require_POST
def account_save(request):
    _require_write(request)
    return views_finance.account_save(request)


@login_required
@require_POST
def record_soft_delete(request, kind, record_id):
    _require_write(request)
    return views_finance.record_soft_delete(request, kind, record_id)


@login_required
@require_POST
def record_restore(request, kind, record_id):
    _require_write(request)
    return views_finance.record_restore(request, kind, record_id)


@login_required
@require_POST
def record_hard_delete(request, kind, record_id):
    _require_tenant_admin(request)
    return views_finance.record_hard_delete(request, kind, record_id)


@login_required
@require_GET
def contract_finance_summary(request, contract_id):
    _require_view(request)
    return views_finance.contract_finance_summary(request, contract_id)
