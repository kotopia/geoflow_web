from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from django.db import connections, transaction
from django.utils import timezone

from control.gf_authz.permissions import gf_has_perm

from .employee_access import current_employee_id
from .project_access import project_access_policy


@dataclass(frozen=True)
class ContractDocumentAccessState:
    allowed: bool
    request_id: str | None = None
    status: str = "none"
    expires_at: object | None = None


def _table_exists(alias: str) -> bool:
    with connections[alias].cursor() as cur:
        cur.execute("SELECT to_regclass('ops.contract_document_access_requests') IS NOT NULL")
        row = cur.fetchone()
    return bool(row and row[0])


def _related_project_allowed(request, alias: str, project_id: str) -> bool:
    return project_access_policy(request, alias).can_view(project_id)


def access_state(request, alias: str, contract_id) -> ContractDocumentAccessState:
    if gf_has_perm(request, "contracts.view"):
        return ContractDocumentAccessState(True, status="permission")
    if not _table_exists(alias):
        return ContractDocumentAccessState(False)

    employee_id = current_employee_id(alias, request)
    if not employee_id:
        return ContractDocumentAccessState(False)

    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT id::text, project_id::text, status, expires_at
              FROM ops.contract_document_access_requests
             WHERE contract_id=%s::uuid
               AND requester_employee_id=%s::uuid
             ORDER BY requested_at DESC
            """,
            [str(contract_id), str(employee_id)],
        )
        rows = cur.fetchall()

    now = timezone.now()
    latest = None
    for row in rows:
        if latest is None:
            latest = row
        if row[2] != "approved":
            continue
        if row[3] is not None and row[3] <= now:
            continue
        if not _related_project_allowed(request, alias, row[1]):
            continue
        return ContractDocumentAccessState(True, row[0], "approved", row[3])

    if latest:
        return ContractDocumentAccessState(False, latest[0], latest[2], latest[3])
    return ContractDocumentAccessState(False)


def request_access(request, alias: str, project_id, reason: str = "") -> str:
    policy = project_access_policy(request, alias)
    if not policy.can_view(project_id):
        raise PermissionError("Project access denied")
    employee_id = current_employee_id(alias, request)
    if not employee_id:
        raise PermissionError("Employee profile required")

    with transaction.atomic(using=alias):
        with connections[alias].cursor() as cur:
            cur.execute(
                "SELECT contract_id::text FROM prj.projects WHERE id=%s::uuid LIMIT 1",
                [str(project_id)],
            )
            row = cur.fetchone()
            if not row or not row[0]:
                raise ValueError("Project contract not found")
            contract_id = row[0]
            cur.execute(
                """
                SELECT id::text
                  FROM ops.contract_document_access_requests
                 WHERE contract_id=%s::uuid
                   AND project_id=%s::uuid
                   AND requester_employee_id=%s::uuid
                   AND status='pending'
                 LIMIT 1
                 FOR UPDATE
                """,
                [contract_id, str(project_id), str(employee_id)],
            )
            existing = cur.fetchone()
            if existing:
                cur.execute(
                    """
                    UPDATE ops.contract_document_access_requests
                       SET reason=%s, requested_at=now(), updated_at=now()
                     WHERE id=%s::uuid
                    """,
                    [reason or None, existing[0]],
                )
                return existing[0]

            cur.execute(
                """
                INSERT INTO ops.contract_document_access_requests
                    (contract_id, project_id, requester_employee_id, reason)
                VALUES (%s::uuid, %s::uuid, %s::uuid, %s)
                RETURNING id::text
                """,
                [contract_id, str(project_id), str(employee_id), reason or None],
            )
            return cur.fetchone()[0]


def pending_requests(alias: str, contract_id) -> list[dict]:
    if not _table_exists(alias):
        return []
    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT r.id::text, r.project_id::text, r.requester_employee_id::text,
                   e.name, e.title, p.name, r.reason, r.requested_at
              FROM ops.contract_document_access_requests r
              LEFT JOIN hr.employee_profile e ON e.id=r.requester_employee_id
              LEFT JOIN prj.projects p ON p.id=r.project_id
             WHERE r.contract_id=%s::uuid
               AND r.status='pending'
             ORDER BY r.requested_at
            """,
            [str(contract_id)],
        )
        rows = cur.fetchall()
    return [
        {
            "id": row[0],
            "project_id": row[1],
            "employee_id": row[2],
            "employee_name": row[3] or "",
            "employee_title": row[4] or "",
            "project_name": row[5] or "",
            "reason": row[6] or "",
            "requested_at": row[7],
        }
        for row in rows
    ]


def decide_request(request, alias: str, request_id, decision: str) -> None:
    if not gf_has_perm(request, "contracts.edit"):
        raise PermissionError("Contract edit permission required")
    if decision not in {"approved", "rejected", "revoked"}:
        raise ValueError("Invalid decision")

    actor = str(
        getattr(getattr(request, "user", None), "email", None)
        or getattr(getattr(request, "user", None), "username", None)
        or "unknown"
    )
    with transaction.atomic(using=alias):
        with connections[alias].cursor() as cur:
            cur.execute(
                "SELECT status FROM ops.contract_document_access_requests WHERE id=%s::uuid FOR UPDATE",
                [str(request_id)],
            )
            row = cur.fetchone()
            if not row:
                raise ValueError("Access request not found")
            expires_at = timezone.now() + timedelta(days=7) if decision == "approved" else None
            cur.execute(
                """
                UPDATE ops.contract_document_access_requests
                   SET status=%s,
                       decided_at=now(),
                       decided_by=%s,
                       expires_at=%s,
                       updated_at=now()
                 WHERE id=%s::uuid
                """,
                [decision, actor, expires_at, str(request_id)],
            )
