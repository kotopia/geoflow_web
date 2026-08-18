from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from control.gf_authz.permissions import gf_has_perm

from .models import Contract
from .services.entity_access import authorize_scope_read, require_tenant_context
from .services.workflow_state import contract_workflow_state, contract_workflow_states
from .views_execution import _load_task_rows


def _payload(state):
    return {
        "contract_id": state.contract_id,
        "major_phase": state.major_phase,
        "major_label": state.major_label,
        "detail_stage": state.detail_stage,
        "detail_label": state.detail_label,
        "source": state.source,
    }


def _task_label(row):
    parts = [row.get("l2_name") or "", row.get("l3_name") or ""]
    return " · ".join(part for part in parts if part) or "업무"


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


@never_cache
@login_required
@require_GET
def project_execution_state(request, pk):
    """Summarize the Project's catalog execution records, not Event stages.

    Project workflow is the selected catalog work itself (e.g. 기준점/측량/
    정위치/구조화). Cross-department transitions remain ProcessEvents below it.
    """

    alias = require_tenant_context(request)
    if not authorize_scope_read(request, alias, "project", pk):
        return JsonResponse({"error": "Forbidden"}, status=403)

    rows = _load_task_rows(alias, pk)
    active = [row for row in rows if row["status"] == "active"]
    pending = [row for row in rows if row["status"] == "pending"]
    hold = [row for row in rows if row["status"] == "hold"]
    open_rows = active + pending + hold
    done_count = sum(1 for row in rows if row["status"] == "done")

    current = active[0] if active else (hold[0] if hold else (pending[0] if pending else None))
    next_row = pending[0] if pending else None
    all_completed = bool(rows) and not open_rows

    current_label = _task_label(current) if current else ("실행업무 완료" if all_completed else "업무범위 미설정")
    next_label = _task_label(next_row) if next_row else ("검사요청 가능" if all_completed else "대기 업무 없음")
    assignee_label = "미지정"
    if current:
        assignee_label = current.get("assignee_name") or "미지정"
        if current.get("assignee_title"):
            assignee_label += " · " + current["assignee_title"]

    return JsonResponse(
        {
            "project_id": str(pk),
            "current_task": current_label,
            "current_status": current.get("status_label") if current else ("완료" if all_completed else "미설정"),
            "next_task": next_label,
            "assignee": assignee_label,
            "open_count": len(open_rows),
            "done_count": done_count,
            "total_count": len(rows),
            "all_completed": all_completed,
        }
    )
