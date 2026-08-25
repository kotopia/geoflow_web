from __future__ import annotations

from django.db import connections

from control.gf_authz.permissions import gf_has_perm

from .employee_access import current_employee_id, effective_roles


MANAGEMENT_ROLES = frozenset({
    "tenant_admin", "tenant_administrator", "tenant_manager", "manager",
    "group_admin", "contract_manager", "admin", "project_admin",
    # Temporary central-role alias while the control DB is migrated.
    "project_manager", "projectmanager", "pm",
})
PROJECT_ROLES = frozenset({
    "project_coordinator", "project_leader",
    "projectleader", "leader", "pl", "worker", "viewer",
})


def _request_table_exists(alias: str) -> bool:
    try:
        with connections[alias].cursor() as cur:
            cur.execute("SELECT to_regclass('ops.contract_document_access_requests') IS NOT NULL")
            row = cur.fetchone()
        return bool(row and row[0])
    except Exception:
        return False


def can_approve_contract_document_access(request) -> bool:
    roles = effective_roles(request)
    return bool(roles & MANAGEMENT_ROLES or gf_has_perm(request, "contracts.edit"))


def _requester_employee_id(alias: str, request) -> str | None:
    value = current_employee_id(alias, request)
    return str(value) if value else None


def access_request_state(alias: str, request, contract_id) -> dict:
    roles = effective_roles(request)
    # Management/contract editors keep direct document access.
    if can_approve_contract_document_access(request):
        return {"allowed": True, "status": "direct", "request_id": None}

    # Non-project roles retain the existing contracts.view semantics.
    if not (roles & PROJECT_ROLES):
        allowed = bool(gf_has_perm(request, "contracts.view"))
        return {"allowed": allowed, "status": "direct" if allowed else "none", "request_id": None}

    # Project roles never gain contract-document access just from a broad legacy
    # contracts.view permission. Before 0024 is applied, fail closed.
    if not _request_table_exists(alias):
        return {"allowed": False, "status": "none", "request_id": None}

    employee_id = _requester_employee_id(alias, request)
    if not employee_id:
        return {"allowed": False, "status": "none", "request_id": None}

    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT id::text, status
              FROM ops.contract_document_access_requests
             WHERE contract_id=%s
               AND requester_employee_id=%s
             ORDER BY requested_at DESC
             LIMIT 1
            """,
            [str(contract_id), employee_id],
        )
        row = cur.fetchone()
    if not row:
        return {"allowed": False, "status": "none", "request_id": None}
    return {"allowed": row[1] == "approved", "status": row[1], "request_id": row[0]}


def can_read_contract_documents(alias: str, request, contract_id) -> bool:
    return bool(access_request_state(alias, request, contract_id)["allowed"])
