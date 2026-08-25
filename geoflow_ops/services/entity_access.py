from __future__ import annotations

from uuid import UUID

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import connections

from control.gf_authz.permissions import gf_has_perm
from control.middleware import current_db_alias

from geoflow_ops.models import Contract, MyOrgUnit, Partner, ProcessEvent, Project

SCOPE_PERMISSIONS = {
    "contract": {"read": "contracts.view", "write": "contracts.edit"},
    "project": {"read": "projects.view", "write": "projects.edit"},
    "partner": {"read": "partners.view", "write": "partners.create"},
    "employee": {"read": "directory.view", "write": "directory.edit"},
    "orgunit": {"read": "directory.view", "write": "directory.edit"},
}


def require_tenant_context(request) -> str:
    """Return the active tenant DB alias or fail closed before tenant data access."""
    alias = current_db_alias()
    central_alias = getattr(settings, "CENTRAL_DB_ALIAS", "default")
    session_alias = request.session.get("tenant_db_alias")
    if not alias or alias == central_alias or not session_alias or session_alias != alias:
        raise PermissionDenied("Tenant access denied.")
    return alias


def _scope_permission(scope_type: str, *, write: bool) -> str | None:
    row = SCOPE_PERMISSIONS.get(str(scope_type or "").strip().lower())
    if not row:
        return None
    return row["write" if write else "read"]


def has_scope_permission(request, scope_type: str, *, write: bool) -> bool:
    code = _scope_permission(scope_type, write=write)
    return bool(code and gf_has_perm(request, code))


def scope_exists(alias: str, scope_type: str, scope_id: UUID) -> bool:
    scope_type = str(scope_type or "").strip().lower()
    if scope_type == "contract":
        return Contract.objects.using(alias).filter(pk=scope_id).exists()
    if scope_type == "project":
        return Project.objects.using(alias).filter(pk=scope_id).exists()
    if scope_type == "partner":
        return Partner.objects.using(alias).filter(pk=scope_id).exists()
    if scope_type == "orgunit":
        return MyOrgUnit.objects.using(alias).filter(pk=scope_id).exists()
    if scope_type == "employee":
        with connections[alias].cursor() as cur:
            cur.execute(
                "SELECT 1 FROM hr.employee_profile WHERE id = %s LIMIT 1",
                [scope_id],
            )
            return cur.fetchone() is not None
    return False


def authorize_scope_read(request, alias: str, scope_type: str, scope_id: UUID) -> bool:
    scope_type = str(scope_type or "").strip().lower()
    if scope_type == "employee":
        from .employee_access import employee_access_policy

        return bool(
            scope_exists(alias, scope_type, scope_id)
            and employee_access_policy(request, alias).can_view(scope_id)
        )
    if scope_type == "project":
        from .project_access import project_access_policy

        return bool(
            has_scope_permission(request, scope_type, write=False)
            and scope_exists(alias, scope_type, scope_id)
            and project_access_policy(request, alias).can_view(scope_id)
        )
    return has_scope_permission(request, scope_type, write=False) and scope_exists(
        alias, scope_type, scope_id
    )


def authorize_scope_write(request, alias: str, scope_type: str, scope_id: UUID) -> bool:
    scope_type = str(scope_type or "").strip().lower()
    if scope_type == "employee":
        from .employee_access import employee_access_policy

        return bool(
            scope_exists(alias, scope_type, scope_id)
            and employee_access_policy(request, alias).can_edit(scope_id)
        )
    if scope_type == "project":
        from .project_access import project_access_policy

        # Project writes are no longer a tenant-wide projects.edit decision.
        # projects.view admits the user to the Project surface; the project-local
        # policy then decides whether this exact project may be edited.
        return bool(
            has_scope_permission(request, scope_type, write=False)
            and scope_exists(alias, scope_type, scope_id)
            and project_access_policy(request, alias).can_edit_project(scope_id)
        )
    return has_scope_permission(request, scope_type, write=True) and scope_exists(
        alias, scope_type, scope_id
    )


def get_event_for_access(request, alias: str, event_id: UUID, *, write: bool):
    event = ProcessEvent.objects.using(alias).filter(pk=event_id).first()
    if not event:
        return None
    allowed = (
        authorize_scope_write(request, alias, event.scope_type, event.scope_id)
        if write
        else authorize_scope_read(request, alias, event.scope_type, event.scope_id)
    )
    return event if allowed else None


def authorize_event_read(request, alias: str, event_id: UUID) -> bool:
    return get_event_for_access(request, alias, event_id, write=False) is not None


def authorize_event_write(request, alias: str, event_id: UUID) -> bool:
    return get_event_for_access(request, alias, event_id, write=True) is not None


def authorize_attachment_read(request, alias: str, attachment) -> bool:
    if attachment.entity_type == "event":
        event = get_event_for_access(request, alias, attachment.entity_id, write=False)
        if not event:
            return False
        if event.scope_type == "contract":
            from .contract_access import can_read_contract_documents

            return can_read_contract_documents(alias, request, event.scope_id)
        return True
    if attachment.entity_type == "contract":
        from .contract_access import can_read_contract_documents

        return bool(
            authorize_scope_read(request, alias, "contract", attachment.entity_id)
            and can_read_contract_documents(alias, request, attachment.entity_id)
        )
    return authorize_scope_read(
        request,
        alias,
        attachment.entity_type,
        attachment.entity_id,
    )


def authorize_attachment_write(
    request,
    alias: str,
    entity_type: str,
    entity_id: UUID,
) -> bool:
    if entity_type == "event":
        return authorize_event_write(request, alias, entity_id)
    return authorize_scope_write(request, alias, entity_type, entity_id)
