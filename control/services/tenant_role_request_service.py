from __future__ import annotations

import uuid
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Protocol

from django.conf import settings
from django.db import connections, transaction
from django.utils import timezone


_FORBIDDEN_ROLE_PREFIXES = ("central_", "sys_", "super_", "root_")
_FORBIDDEN_ROLE_CODES = {"central_admin", "system_admin", "super_admin", "owner"}


class TenantRoleRequestRejected(Exception):
    """Fail-closed role-request eligibility or state failure."""


@dataclass(frozen=True)
class TenantRoleRequest:
    requester_user_id: str = field(repr=False)
    group_id: str = field(repr=False)
    requested_email: str = field(repr=False)
    role_code: str


class TenantRoleRequestRepository(Protocol):
    alias: str

    def upsert(self, *, request: TenantRoleRequest, changed_at) -> bool: ...


class SqlTenantRoleRequestRepository:
    def __init__(self, alias: str | None = None):
        self.alias = alias or getattr(settings, "CENTRAL_DB_ALIAS", "default")

    def _column_exists(self, cursor, table: str, column: str) -> bool:
        cursor.execute(
            """
            SELECT 1
              FROM information_schema.columns
             WHERE table_schema='public'
               AND table_name=%s
               AND column_name=%s
             LIMIT 1
            """,
            [table, column],
        )
        return cursor.fetchone() is not None

    def upsert(self, *, request: TenantRoleRequest, changed_at) -> bool:
        request_id = str(uuid.uuid4())
        with connections[self.alias].cursor() as cursor:
            role_status_clause = (
                "AND lower(COALESCE(requested_role.status, ''))='active'"
                if self._column_exists(cursor, "roles", "status")
                else ""
            )
            cursor.execute(
                f"""
                WITH eligible AS (
                    SELECT requester.id AS user_id,
                           active_group.id AS group_id,
                           requested_role.code AS role_code
                      FROM users AS requester
                      JOIN groups AS active_group
                        ON active_group.id=%s
                       AND lower(COALESCE(active_group.status, ''))='active'
                      JOIN roles AS requested_role
                        ON requested_role.code=%s
                       {role_status_clause}
                     WHERE requester.id=%s
                       AND requester.is_active=TRUE
                       AND requester.email_verified=TRUE
                       AND requester.password_hash IS NOT NULL
                       AND length(trim(requester.password_hash)) > 0
                       AND (
                           requester.password_hash LIKE 'pbkdf2_sha256$%'
                           OR requester.password_hash LIKE 'bcrypt_sha256$%'
                           OR requester.password_hash LIKE '$2a$%'
                           OR requester.password_hash LIKE '$2b$%'
                           OR requester.password_hash LIKE '$2y$%'
                       )
                     FOR KEY SHARE OF requester, active_group, requested_role
                )
                INSERT INTO join_requests (
                    id, user_id, group_id, requested_email,
                    requested_role_code, status, decided_at, decided_by,
                    created_at, updated_at
                )
                SELECT %s, user_id, group_id, %s,
                       role_code, 'pending', NULL, NULL, %s, %s
                  FROM eligible
                ON CONFLICT (user_id, group_id, requested_email)
                DO UPDATE SET requested_role_code=EXCLUDED.requested_role_code,
                              status='pending',
                              decided_at=NULL,
                              decided_by=NULL,
                              updated_at=EXCLUDED.updated_at
                RETURNING id
                """,
                [
                    request.group_id,
                    request.role_code,
                    request.requester_user_id,
                    request_id,
                    request.requested_email,
                    changed_at,
                    changed_at,
                ],
            )
            return cursor.fetchone() is not None


def _normalize_role_code(value: str) -> str:
    role_code = str(value).strip()
    lowered = role_code.lower()
    if not role_code:
        raise ValueError("role_code is required")
    if lowered.startswith(_FORBIDDEN_ROLE_PREFIXES) or lowered in _FORBIDDEN_ROLE_CODES:
        raise TenantRoleRequestRejected("requested role is not tenant-assignable")
    return role_code


def queue_tenant_role_request(
    request: TenantRoleRequest,
    *,
    repository: TenantRoleRequestRepository | None = None,
    atomic_context: AbstractContextManager | None = None,
) -> None:
    requester_user_id = str(request.requester_user_id).strip()
    group_id = str(request.group_id).strip()
    requested_email = str(request.requested_email).strip().lower()
    if not requester_user_id or not group_id or not requested_email:
        raise ValueError("requester, group and requested email are required")
    role_code = _normalize_role_code(request.role_code)

    normalized = TenantRoleRequest(
        requester_user_id=requester_user_id,
        group_id=group_id,
        requested_email=requested_email,
        role_code=role_code,
    )
    repository = repository or SqlTenantRoleRequestRepository()
    alias = getattr(repository, "alias", getattr(settings, "CENTRAL_DB_ALIAS", "default"))
    context = atomic_context or transaction.atomic(using=alias)
    changed_at = timezone.now()
    with context:
        if not repository.upsert(request=normalized, changed_at=changed_at):
            raise TenantRoleRequestRejected("tenant role request could not be queued")
