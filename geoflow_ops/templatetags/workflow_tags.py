from __future__ import annotations

from django import template
from django.db import connections

from control.middleware import current_db_alias
from geoflow_ops.services.contract_access import (
    access_request_state,
    can_approve_contract_document_access,
)
from geoflow_ops.services.workflow_state import contract_workflow_summaries

register = template.Library()


@register.simple_tag(takes_context=True)
def contract_workflow(context, contract):
    request = context.get("request")
    alias = current_db_alias()
    if not request or not alias or not contract:
        return {"major_label": "-", "stage_label": "-", "major_code": "", "stage": ""}
    cache = getattr(request, "_gf_contract_workflow_cache", None)
    if cache is None:
        rows = context.get("contracts")
        if rows is None:
            rows = [contract]
        else:
            rows = list(rows)
        cache = contract_workflow_summaries(alias, rows)
        request._gf_contract_workflow_cache = cache
    return cache.get(str(contract.id), {"major_label": "-", "stage_label": "-", "major_code": "", "stage": ""})


@register.simple_tag(takes_context=True)
def contract_document_access(context, contract_id):
    request = context.get("request")
    alias = current_db_alias()
    if not request or not alias or not contract_id:
        return {"allowed": False, "status": "none", "request_id": None, "can_approve": False, "pending": []}
    state = access_request_state(alias, request, contract_id)
    state["can_approve"] = can_approve_contract_document_access(request)
    state["pending"] = []
    if state["can_approve"]:
        with connections[alias].cursor() as cur:
            cur.execute(
                """
                SELECT r.id::text, e.name, e.email, r.reason, r.requested_at
                  FROM ops.contract_document_access_requests r
                  LEFT JOIN hr.employee_profile e ON e.id=r.requester_employee_id
                 WHERE r.contract_id=%s AND r.status='pending'
                 ORDER BY r.requested_at
                """,
                [str(contract_id)],
            )
            state["pending"] = [
                {"id": row[0], "name": row[1] or row[2] or "-", "email": row[2] or "", "reason": row[3] or "", "requested_at": row[4]}
                for row in cur.fetchall()
            ]
    return state
