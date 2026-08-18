from __future__ import annotations

from django.db import connections


MANAGEMENT_DEPARTMENT_NAME = "관리부"
MANAGEMENT_EVENT_TYPES = {
    "kickoff_doc",
    "inspection_request",
    "inspection",
    "correction_request",
    "reinspection",
    "completion_doc",
    "delivery",
    "advance_payment",
    "progress_invoice",
    "invoice",
    "tax_invoice",
    "payment",
}


def scope_org_unit_id(alias: str, scope_type: str, scope_id) -> str | None:
    scope_type = str(scope_type or "").strip().lower()
    with connections[alias].cursor() as cur:
        if scope_type == "contract":
            cur.execute("SELECT org_unit_id::text FROM ctr.contracts WHERE id=%s LIMIT 1", [str(scope_id)])
        elif scope_type == "project":
            cur.execute(
                """
                SELECT c.org_unit_id::text
                  FROM prj.projects p
                  JOIN ctr.contracts c ON c.id=p.contract_id
                 WHERE p.id=%s
                 LIMIT 1
                """,
                [str(scope_id)],
            )
        else:
            return None
        row = cur.fetchone()
    return row[0] if row and row[0] else None


def department_id_by_name(alias: str, name: str, *, org_unit_id: str | None = None) -> str | None:
    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT id::text
              FROM hr.departments
             WHERE active=true AND name=%s
               AND (%s IS NULL OR org_unit_id=%s::uuid)
             ORDER BY created_at
             LIMIT 1
            """,
            [name, org_unit_id, org_unit_id],
        )
        row = cur.fetchone()
    return row[0] if row else None


def employee_department_id(alias: str, request) -> str | None:
    user = getattr(request, "user", None)
    identity = str(
        getattr(user, "email", None) or getattr(user, "username", None) or ""
    ).strip().lower()
    if not identity:
        return None
    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT department_id::text
              FROM hr.employee_profile
             WHERE lower(email)=lower(%s)
               AND department_id IS NOT NULL
             LIMIT 1
            """,
            [identity],
        )
        row = cur.fetchone()
    return row[0] if row else None


def default_owner_department_id(alias: str, request, *, event_type: str, scope_type: str, scope_id) -> str | None:
    event_type = str(event_type or "").strip()
    if event_type in MANAGEMENT_EVENT_TYPES:
        org_unit_id = scope_org_unit_id(alias, scope_type, scope_id)
        return department_id_by_name(alias, MANAGEMENT_DEPARTMENT_NAME, org_unit_id=org_unit_id)
    # Field kickoff/execution belongs to the business unit that performs the work.
    if scope_type == "project" or event_type == "kickoff":
        return employee_department_id(alias, request)
    return None


def route_project_inspection_request_to_management(alias: str, project_id) -> str | None:
    org_unit_id = scope_org_unit_id(alias, "project", project_id)
    return department_id_by_name(alias, MANAGEMENT_DEPARTMENT_NAME, org_unit_id=org_unit_id)
