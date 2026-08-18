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


def department_id_by_name(alias: str, name: str) -> str | None:
    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT id::text
              FROM hr.departments
             WHERE active=true AND name=%s
             ORDER BY org_unit_id NULLS LAST, created_at
             LIMIT 1
            """,
            [name],
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


def default_owner_department_id(alias: str, request, *, event_type: str, scope_type: str) -> str | None:
    event_type = str(event_type or "").strip()
    if event_type in MANAGEMENT_EVENT_TYPES:
        return department_id_by_name(alias, MANAGEMENT_DEPARTMENT_NAME)
    # Field kickoff/execution belongs to the business unit that performs the work.
    if scope_type == "project" or event_type == "kickoff":
        return employee_department_id(alias, request)
    return None


def route_project_inspection_request_to_management(alias: str) -> str | None:
    return department_id_by_name(alias, MANAGEMENT_DEPARTMENT_NAME)
