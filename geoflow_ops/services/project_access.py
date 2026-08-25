from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.db import connections

from control.gf_authz.permissions import gf_has_perm

from .employee_access import current_employee_id, effective_roles


FULL_PROJECT_ROLES = frozenset({
    "tenant_admin",
    "tenant_administrator",
    "tenant_manager",
    "manager",
    "group_admin",
    "project_admin",
    # Temporary central-role aliases while the control DB is migrated.
    "project_manager",
    "projectmanager",
    "pm",
})
PROJECT_COORDINATOR_ROLES = frozenset({
    "project_coordinator",
    # Temporary central-role aliases while the control DB is migrated.
    "project_leader",
    "projectleader",
    "leader",
    "pl",
})
WORKER_ROLES = frozenset({"worker", "project_worker", "projectworker"})
VIEWER_ROLES = frozenset({"viewer", "project_viewer", "projectviewer"})
PROJECT_MEMBER_ROLES = frozenset({"project_manager", "project_leader", "worker", "viewer"})


def _table_exists(alias: str, relation: str) -> bool:
    with connections[alias].cursor() as cur:
        cur.execute("SELECT to_regclass(%s) IS NOT NULL", [relation])
        row = cur.fetchone()
    return bool(row and row[0])


def _login_identity(request) -> str:
    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        return ""
    return str(getattr(user, "email", None) or getattr(user, "username", None) or "").strip().lower()


def _current_employee_id(alias: str, request) -> str | None:
    cache = getattr(request, "_gf_project_employee_id_cache", None)
    if cache is None:
        cache = {}
        setattr(request, "_gf_project_employee_id_cache", cache)
    if alias not in cache:
        cache[alias] = current_employee_id(alias, request)
    return cache[alias]


def active_memberships_for_request(alias: str, request) -> dict[str, dict]:
    """Load all active project memberships for this login once per request."""
    cache = getattr(request, "_gf_project_memberships_cache", None)
    if cache is None:
        cache = {}
        setattr(request, "_gf_project_memberships_cache", cache)
    if alias in cache:
        return cache[alias]

    if not _table_exists(alias, "prj.project_members"):
        cache[alias] = {}
        return cache[alias]

    employee_id = _current_employee_id(alias, request)
    identity = _login_identity(request)
    if not employee_id and not identity:
        cache[alias] = {}
        return cache[alias]

    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT id::text, project_id::text, employee_id::text, member_role,
                   membership_status, invite_email, invite_name, is_external
              FROM prj.project_members
             WHERE membership_status='active'
               AND (
                    (%s IS NOT NULL AND employee_id=%s::uuid)
                    OR (%s <> '' AND employee_id IS NULL AND lower(invite_email)=lower(%s))
               )
             ORDER BY project_id,
                      CASE member_role
                        WHEN 'project_manager' THEN 1
                        WHEN 'project_leader' THEN 2
                        WHEN 'worker' THEN 3
                        ELSE 4
                      END,
                      updated_at DESC
            """,
            [employee_id, employee_id, identity, identity],
        )
        rows = cur.fetchall()

    memberships: dict[str, dict] = {}
    for row in rows:
        project_id = row[1]
        if project_id in memberships:
            continue
        memberships[project_id] = {
            "id": row[0],
            "project_id": project_id,
            "employee_id": row[2],
            "member_role": row[3],
            "membership_status": row[4],
            "invite_email": row[5] or "",
            "invite_name": row[6] or "",
            "is_external": bool(row[7]),
        }
    cache[alias] = memberships
    return memberships


def _membership_row(alias: str, request, project_id) -> dict | None:
    return active_memberships_for_request(alias, request).get(str(project_id))


def active_project_ids_for_request(alias: str, request) -> list[str]:
    return sorted(active_memberships_for_request(alias, request).keys())


@dataclass(frozen=True)
class ProjectAccessPolicy:
    alias: str
    request: object
    mode: str
    self_employee_id: str | None

    @property
    def can_view_all(self) -> bool:
        return self.mode in {"full", "leader"}

    @property
    def can_edit_all(self) -> bool:
        return self.mode == "full"

    def membership(self, project_id) -> dict | None:
        try:
            UUID(str(project_id))
        except (TypeError, ValueError, AttributeError):
            return None
        return _membership_row(self.alias, self.request, project_id)

    def can_view(self, project_id) -> bool:
        if self.can_view_all:
            return True
        return self.membership(project_id) is not None

    def can_edit_project(self, project_id) -> bool:
        if self.can_edit_all:
            return True
        if self.mode == "leader":
            return self.membership(project_id) is not None
        member = self.membership(project_id)
        return bool(member and member["member_role"] in {"project_manager", "project_leader"})

    def can_webgis_read(self, project_id) -> bool:
        return self.can_view(project_id)

    def can_webgis_write(self, project_id) -> bool:
        if self.can_edit_all:
            return True
        member = self.membership(project_id)
        if not member:
            return False
        if self.mode == "viewer":
            return False
        if self.mode == "leader":
            return True
        return member["member_role"] in {"project_manager", "project_leader", "worker"}

    def can_manage_members(self, project_id) -> bool:
        if self.can_edit_all:
            return True
        return bool(self.mode == "leader" and self.membership(project_id))

    def assignable_member_roles(self, project_id) -> tuple[str, ...]:
        if self.can_edit_all:
            return ("project_manager", "project_leader", "worker", "viewer")
        if self.can_manage_members(project_id):
            return ("worker", "viewer")
        return ()

    def visible_project_ids(self) -> list[str] | None:
        if self.can_view_all:
            return None
        return active_project_ids_for_request(self.alias, self.request)


def project_access_policy(request, alias: str) -> ProjectAccessPolicy:
    roles = effective_roles(request)
    employee_id = _current_employee_id(alias, request)

    if roles & FULL_PROJECT_ROLES:
        mode = "full"
    elif roles & PROJECT_COORDINATOR_ROLES:
        mode = "leader"
    elif roles & VIEWER_ROLES:
        mode = "viewer"
    elif roles & WORKER_ROLES:
        mode = "worker"
    else:
        # Compatibility only for older tenants without canonical role codes.
        # Recognized Worker/Viewer/Leader roles above always win, preventing a
        # stale broad permission from expanding their project scope.
        if gf_has_perm(request, "projects.edit"):
            mode = "full"
        elif gf_has_perm(request, "projects.view"):
            mode = "viewer"
        else:
            mode = "viewer"

    return ProjectAccessPolicy(
        alias=alias,
        request=request,
        mode=mode,
        self_employee_id=employee_id,
    )
