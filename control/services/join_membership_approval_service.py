from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Protocol

from django.conf import settings
from django.db import connections, transaction
from django.utils import timezone


class JoinMembershipApprovalRejected(Exception):
    """Fail-closed join approval conflict or eligibility failure."""


@dataclass(frozen=True)
class JoinMembershipApproval:
    request_id: str = field(repr=False)
    user_id: str = field(repr=False)
    group_id: str = field(repr=False)
    role_id: str = field(repr=False)
    actor_user_id: str = field(repr=False)


class JoinMembershipApprovalRepository(Protocol):
    alias: str

    def apply(self, *, approval: JoinMembershipApproval, decided_at) -> bool: ...


class SqlJoinMembershipApprovalRepository:
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

    def _decider_column(self, cursor) -> str | None:
        for column in ("decided_by", "decided_by_user_id"):
            if self._column_exists(cursor, "join_requests", column):
                return column
        return None

    def apply(self, *, approval: JoinMembershipApproval, decided_at) -> bool:
        with connections[self.alias].cursor() as cursor:
            decider_column = self._decider_column(cursor)
            if decider_column is None:
                return False
            decider_assignment = f", {decider_column}=%s"
            decider_params = [approval.actor_user_id]
            role_status_clause = ""
            if self._column_exists(cursor, "roles", "status"):
                role_status_clause = (
                    "AND lower(COALESCE(requested_role.status, ''))='active'"
                )
            cursor.execute(
                f"""
                WITH eligible AS (
                    SELECT join_request.id,
                           signup_user.id AS user_id,
                           active_group.id AS group_id,
                           requested_role.id AS role_id
                      FROM join_requests AS join_request
                      JOIN users AS signup_user
                        ON signup_user.id=%s
                       AND lower(signup_user.email)=lower(join_request.requested_email)
                       AND signup_user.is_active=TRUE
                       AND signup_user.email_verified=TRUE
                       AND signup_user.password_hash IS NOT NULL
                       AND length(trim(signup_user.password_hash)) > 0
                       AND (
                           signup_user.password_hash LIKE 'pbkdf2_sha256$%'
                           OR signup_user.password_hash LIKE 'bcrypt_sha256$%'
                           OR signup_user.password_hash LIKE '$2a$%'
                           OR signup_user.password_hash LIKE '$2b$%'
                           OR signup_user.password_hash LIKE '$2y$%'
                       )
                      JOIN groups AS active_group
                        ON active_group.id=join_request.group_id
                       AND active_group.id=%s
                       AND lower(COALESCE(active_group.status, ''))='active'
                      JOIN roles AS requested_role
                        ON requested_role.id=%s
                       AND requested_role.code=join_request.requested_role_code
                       {role_status_clause}
                      JOIN users AS approval_actor
                        ON approval_actor.id=%s
                       AND approval_actor.is_active=TRUE
                       AND approval_actor.is_staff=TRUE
                     WHERE join_request.id=%s
                       AND join_request.status='pending'
                     FOR UPDATE OF join_request, signup_user, active_group, requested_role, approval_actor
                ), membership AS (
                    INSERT INTO user_group_map (
                        id, user_id, group_id, role_id, status, created_at, updated_at
                    )
                    SELECT gen_random_uuid(), user_id, group_id, role_id,
                           'active', %s, %s
                      FROM eligible
                    ON CONFLICT (user_id, group_id)
                    DO UPDATE SET role_id=EXCLUDED.role_id,
                                  status='active',
                                  updated_at=EXCLUDED.updated_at
                    RETURNING user_id, group_id
                )
                UPDATE join_requests AS join_request
                   SET status='approved',
                       updated_at=%s,
                       decided_at=%s
                       {decider_assignment}
                  FROM eligible, membership
                 WHERE join_request.id=eligible.id
                   AND membership.user_id=eligible.user_id
                   AND membership.group_id=eligible.group_id
                   AND join_request.status='pending'
                RETURNING join_request.id
                """,
                [
                    approval.user_id,
                    approval.group_id,
                    approval.role_id,
                    approval.actor_user_id,
                    approval.request_id,
                    decided_at,
                    decided_at,
                    decided_at,
                    decided_at,
                    *decider_params,
                ],
            )
            return cursor.fetchone() is not None


def approve_join_membership(
    approval: JoinMembershipApproval,
    *,
    repository: JoinMembershipApprovalRepository | None = None,
    atomic_context: AbstractContextManager | None = None,
) -> None:
    for value, label in (
        (approval.request_id, "request_id"),
        (approval.user_id, "user_id"),
        (approval.group_id, "group_id"),
        (approval.role_id, "role_id"),
        (approval.actor_user_id, "actor_user_id"),
    ):
        if not str(value).strip():
            raise ValueError(f"{label} is required")

    repository = repository or SqlJoinMembershipApprovalRepository()
    alias = getattr(
        repository,
        "alias",
        getattr(settings, "CENTRAL_DB_ALIAS", "default"),
    )
    context = atomic_context or transaction.atomic(using=alias)
    decided_at = timezone.now()
    with context:
        if not repository.apply(approval=approval, decided_at=decided_at):
            raise JoinMembershipApprovalRejected(
                "join membership approval could not be applied"
            )
