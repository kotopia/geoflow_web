from __future__ import annotations

from uuid import UUID

from django.db import connections

from geoflow_ops.process_workflow import normalize_stage


MANAGEMENT_DEPARTMENT_NAME = "관리부"

# Event status stays in the database as workflow metadata, but the UI does not
# ask users to classify every event manually. Only request-like events remain
# open; ordinary business records are completed when recorded.
OPEN_EVENT_TYPES = frozenset({
    "inspection_request",
    "correction_request",
    "reinspection",
})


def default_event_status(event_type: object) -> str:
    return "open" if str(event_type or "").strip() in OPEN_EVENT_TYPES else "done"


def _project_id_for_scope(alias: str, scope_type: str, scope_id: UUID) -> str | None:
    if scope_type == "project":
        return str(scope_id)
    return None


def _contract_org_unit_id(alias: str, scope_type: str, scope_id: UUID) -> str | None:
    with connections[alias].cursor() as cur:
        if scope_type == "contract":
            cur.execute("SELECT org_unit_id::text FROM ctr.contracts WHERE id=%s LIMIT 1", [str(scope_id)])
        elif scope_type == "project":
            cur.execute(
                """
                SELECT c.org_unit_id::text
                  FROM prj.projects p
                  JOIN ctr.contracts c ON c.id=p.contract_id
                 WHERE p.id=%s LIMIT 1
                """,
                [str(scope_id)],
            )
        else:
            return None
        row = cur.fetchone()
    return row[0] if row and row[0] else None


def _department_by_name(alias: str, org_unit_id: str | None, name: str) -> str | None:
    if not org_unit_id:
        return None
    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT id::text
              FROM hr.departments
             WHERE org_unit_id=%s::uuid
               AND active=true
               AND btrim(name)=%s
             ORDER BY created_at
             LIMIT 1
            """,
            [org_unit_id, name],
        )
        row = cur.fetchone()
    return row[0] if row else None


def _project_business_department(alias: str, project_id: str | None) -> str | None:
    if not project_id:
        return None
    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT e.department_id::text
              FROM prj.project_members m
              JOIN hr.employee_profile e ON e.id=m.employee_id
             WHERE m.project_id=%s::uuid
               AND m.membership_status='active'
               AND m.employee_id IS NOT NULL
               AND e.department_id IS NOT NULL
               AND (e.status IS NULL OR e.status <> '퇴사')
             ORDER BY CASE m.member_role
                        WHEN 'project_manager' THEN 1
                        WHEN 'project_leader' THEN 2
                        WHEN 'worker' THEN 3
                        ELSE 4
                      END,
                      m.updated_at DESC
             LIMIT 1
            """,
            [project_id],
        )
        row = cur.fetchone()
    return row[0] if row else None


def default_owner_department_id(
    alias: str,
    scope_type: str,
    scope_id: UUID,
    stage: object,
    event_type: object,
) -> str | None:
    """Return the operational handoff department for a new event.

    Administrative records live with 관리부. Project execution lives with the
    project's PM/Leader department. Inspection requests hand work back to
    관리부; correction requests hand it back to the project business department.
    """

    stage = normalize_stage(stage)
    event_type = str(event_type or "").strip()
    org_unit_id = _contract_org_unit_id(alias, scope_type, scope_id)
    management = _department_by_name(alias, org_unit_id, MANAGEMENT_DEPARTMENT_NAME)
    project_id = _project_id_for_scope(alias, scope_type, scope_id)
    business = _project_business_department(alias, project_id)

    if event_type == "correction_request":
        return business or management
    if event_type in {"inspection_request", "inspection", "reinspection"}:
        return management or business
    if stage == "execution":
        return business or management
    if stage == "kickoff" and event_type == "kickoff":
        return business or management
    return management or business


def complete_prior_handoff_events(alias: str, event) -> int:
    """Close the request being answered by a newly recorded handoff event."""

    event_type = str(event.event_type or "").strip()
    prior_types: set[str] = set()
    if event_type == "correction_request":
        prior_types = {"inspection_request", "reinspection"}
    elif event_type == "reinspection":
        prior_types = {"correction_request"}
    elif event_type == "inspection":
        prior_types = {"inspection_request", "reinspection"}
    if not prior_types:
        return 0

    params = [str(event.contract_id) if event.contract_id else None]
    sql = """
        UPDATE ops.process_events
           SET status='done', updated_at=now()
         WHERE status='open'
           AND event_type = ANY(%s)
           AND contract_id=%s::uuid
    """
    with connections[alias].cursor() as cur:
        cur.execute(sql, [list(prior_types), params[0]])
        return int(cur.rowcount or 0)
