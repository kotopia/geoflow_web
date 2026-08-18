from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from control.gf_authz.permissions import gf_has_perm

from .models import Contract
from .services.entity_access import require_tenant_context
from .services.workflow_state import contract_workflow_state, contract_workflow_states


def _payload(state):
    return {
        "contract_id": state.contract_id,
        "major_phase": state.major_phase,
        "major_label": state.major_label,
        "detail_stage": state.detail_stage,
        "detail_label": state.detail_label,
        "source": state.source,
    }


@never_cache
@login_required
@require_GET
def contract_state(request, pk):
    alias = require_tenant_context(request)
    if not gf_has_perm(request, "contracts.view"):
        return JsonResponse({"error": "Forbidden"}, status=403)
    contract = Contract.objects.using(alias).filter(pk=pk).first()
    if not contract:
        return JsonResponse({"error": "Not found"}, status=404)
    return JsonResponse(_payload(contract_workflow_state(alias, contract)))


@never_cache
@login_required
@require_GET
def contract_states(request):
    alias = require_tenant_context(request)
    if not gf_has_perm(request, "contracts.view"):
        return JsonResponse({"error": "Forbidden"}, status=403)

    raw_ids = [value for value in request.GET.getlist("id") if value]
    qs = Contract.objects.using(alias).only("id", "status")
    if raw_ids:
        qs = qs.filter(pk__in=raw_ids[:1000])
    contracts = list(qs)
    states = contract_workflow_states(alias, contracts)
    return JsonResponse({"states": {key: _payload(value) for key, value in states.items()}})
