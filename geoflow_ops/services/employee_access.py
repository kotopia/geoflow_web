from __future__ import annotations

from dataclasses import dataclass

from django.db import connections

from control.gf_authz.permissions import gf_has_perm


FULL_MANAGER_ROLES = frozenset({
    "tenant_admin",
    "tenant_administrator",
    "tenant_manager",
    "manager",
    "group_admin",
})
PROJECT_ADMIN_ROLES = frozenset({
    "project_admin",
    # Temporary central-role aliases while the control DB is migrated.
    "project_manager", "projectmanager", "pm",
})
SELF_ONLY_ROLES = frozenset({
    "project_coordinator",
    "project_leader",
    "projectleader",
    "leader",
    "viewer",
    "project_viewer",
    "projectviewer",
})


def _normalize_role(value: str) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def effective_roles(request) -> set[str]:
    cached = getattr(request, "_gf_roles_cache", None)
    if cached is None:
        cached = request.session.get("gf_roles") or []
    return {_normalize_role(role) for role in cached if str(role or "").strip()}


def current_employee_id(alias: str, request) -> str | None:
    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        return None
    identity = str(
        getattr(user, "email", None)
        or getattr(user, "username", None)
        or ""
    ).strip().lower()
    if not identity:
        return None
    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT id::text
              FROM hr.employee_profile
             WHERE lower(email) = lower(%s)
             ORDER BY updated_at DESC NULLS LAST, created_at DESC NULLS LAST
             LIMIT 1
            """,
            [identity],
        )
        row = cur.fetchone()
    return row[0] if row else None


@dataclass(frozen=True)
class EmployeeAccessPolicy:
    self_employee_id: str | None
    mode: str
    can_list: bool
    can_create: bool
    can_manage_settings: bool
    can_assign_roles: bool

    def can_view(self, employee_id) -> bool:
        target = str(employee_id or "")
        if self.mode in {"full", "all_view"}:
            return bool(target)
        return bool(self.self_employee_id and target == str(self.self_employee_id))

    def can_edit(self, employee_id) -> bool:
        target = str(employee_id or "")
        if self.mode == "full":
            return bool(target)
        return bool(self.self_employee_id and target == str(self.self_employee_id))

    def can_edit_admin_fields(self, employee_id) -> bool:
        return bool(self.mode == "full" and self.can_edit(employee_id))


def employee_access_policy(request, alias: str) -> EmployeeAccessPolicy:
    roles = effective_roles(request)
    self_id = current_employee_id(alias, request)

    if roles & FULL_MANAGER_ROLES:
        mode = "full"
    elif roles & PROJECT_ADMIN_ROLES:
        mode = "all_view"
    elif roles & SELF_ONLY_ROLES:
        mode = "self"
    else:
        # Preserve compatibility for tenants whose central role codes predate the
        # canonical names above. Explicit role families always win over this
        # permission fallback, so a recognized Project Manager can never edit
        # somebody else's employee record merely because of stale permissions.
        if gf_has_perm(request, "directory.edit"):
            mode = "full"
        elif gf_has_perm(request, "directory.view"):
            mode = "all_view"
        else:
            mode = "self"

    can_list = mode in {"full", "all_view"}
    can_create = mode == "full"
    return EmployeeAccessPolicy(
        self_employee_id=self_id,
        mode=mode,
        can_list=can_list,
        can_create=can_create,
        can_manage_settings=mode == "full",
        can_assign_roles=bool(mode == "full" and gf_has_perm(request, "directory.roles.assign")),
    )
