from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.views.decorators.http import require_GET, require_POST

from control.gf_authz.permissions import gf_has_perm

from . import views_finance
from .services.entity_access import require_tenant_context


def _require_view(request):
    require_tenant_context(request)
    if not gf_has_perm(request, "contracts.view"):
        raise PermissionDenied("Permission denied")


def _require_write(request):
    require_tenant_context(request)
    if not (gf_has_perm(request, "contracts.edit") or gf_has_perm(request, "contracts.create")):
        raise PermissionDenied("Permission denied")


@login_required
@require_GET
def finance_page(request):
    _require_view(request)
    return views_finance.finance_page(request)


@login_required
@require_POST
def claim_save(request):
    _require_write(request)
    return views_finance.claim_save(request)


@login_required
@require_POST
def invoice_save(request):
    _require_write(request)
    return views_finance.invoice_save(request)


@login_required
@require_POST
def payment_request_save(request):
    _require_write(request)
    return views_finance.payment_request_save(request)


@login_required
@require_POST
def transaction_save(request):
    _require_write(request)
    return views_finance.transaction_save(request)


@login_required
@require_POST
def account_save(request):
    _require_write(request)
    return views_finance.account_save(request)


@login_required
@require_GET
def contract_finance_summary(request, contract_id):
    _require_view(request)
    return views_finance.contract_finance_summary(request, contract_id)
