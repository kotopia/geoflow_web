from __future__ import annotations

from dataclasses import dataclass, field
import uuid
from datetime import datetime
from typing import Protocol

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import connections, transaction
from django.utils import timezone


TERMINAL_RETENTION_STATUSES = ("rejected", "expired")


@dataclass(frozen=True)
class SignupRetentionCandidate:
    signup_request_id: str = field(repr=False)
    user_id: str = field(repr=False)
    status: str
    retention_started_at: datetime


@dataclass(frozen=True)
class SignupRetentionResult:
    candidates: int
    purged: int
    dry_run: bool


class SignupRetentionRepository(Protocol):
    alias: str

    def list_candidates(
        self,
        *,
        cutoff: datetime,
        batch_size: int,
    ) -> tuple[SignupRetentionCandidate, ...]: ...

    def purge_candidate(self, candidate: SignupRetentionCandidate) -> None: ...


class CentralSignupRetentionRepository:
    """Strictly purge terminal signup-only identities after one calendar year.

    Candidate selection excludes identities that have become authoritative elsewhere:
    another signup request, group membership/ownership, join-request linkage or decision
    responsibility, or signup audit-actor responsibility. The final delete repeats the
    same safety checks and locks the request/user rows before dependency removal.
    """

    def __init__(self, alias: str | None = None):
        self.alias = alias or getattr(settings, "CENTRAL_DB_ALIAS", "default")

    def _table_exists(self, cursor, table: str) -> bool:
        cursor.execute("SELECT to_regclass(%s)", [f"public.{table}"])
        row = cursor.fetchone()
        return bool(row and row[0])

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

    def _join_request_email_columns(self, cursor) -> tuple[str, ...]:
        return tuple(
            column
            for column in ("requested_email", "email")
            if self._column_exists(cursor, "join_requests", column)
        )

    def _join_request_decider_columns(self, cursor) -> tuple[str, ...]:
        return tuple(
            column
            for column in ("decided_by_user_id", "decided_by")
            if self._column_exists(cursor, "join_requests", column)
        )

    def _dynamic_safety_clauses(self, cursor) -> tuple[str, str, str]:
        join_email_clause = "".join(
            f" OR lower(join_request.{column})=lower(signup_user.email)"
            for column in self._join_request_email_columns(cursor)
        )
        join_decider_clause = "".join(
            f"""
                   AND NOT EXISTS (
                       SELECT 1 FROM join_requests AS decided_join_request
                        WHERE decided_join_request.{column}=signup_user.id
                   )
            """
            for column in self._join_request_decider_columns(cursor)
        )
        group_owner_clause = (
            """
                   AND NOT EXISTS (
                       SELECT 1 FROM groups AS owned_group
                        WHERE owned_group.owner_user_id=signup_user.id
                   )
            """
            if self._column_exists(cursor, "groups", "owner_user_id")
            else ""
        )
        return join_email_clause, join_decider_clause, group_owner_clause

    def _anonymize_django_session_bridge(self, cursor, *, email: str) -> None:
        if not self._table_exists(cursor, "auth_user"):
            return
        cursor.execute(
            """
            SELECT id
              FROM auth_user
             WHERE lower(COALESCE(username, ''))=lower(%s)
             FOR UPDATE
            """,
            [email],
        )
        for (bridge_id,) in cursor.fetchall():
            cursor.execute(
                """
                UPDATE auth_user
                   SET username=%s, email='', password=%s,
                       first_name='', last_name='', last_login=NULL,
                       is_active=FALSE, is_staff=FALSE, is_superuser=FALSE
                 WHERE id=%s
                """,
                [
                    f"erased-session-{uuid.uuid4()}@example.invalid",
                    make_password(None),
                    bridge_id,
                ],
            )
        cursor.execute(
            """
            UPDATE auth_user
               SET email=''
             WHERE lower(COALESCE(email, ''))=lower(%s)
               AND lower(COALESCE(username, ''))<>lower(%s)
            """,
            [email, email],
        )

    def _delete_legacy_password_tokens(self, cursor, *, user_id: str) -> None:
        for table in ("password_reset_tokens", "user_tokens"):
            if self._table_exists(cursor, table):
                cursor.execute(f"DELETE FROM {table} WHERE user_id=%s", [user_id])

    def list_candidates(
        self,
        *,
        cutoff: datetime,
        batch_size: int,
    ) -> tuple[SignupRetentionCandidate, ...]:
        with connections[self.alias].cursor() as cursor:
            join_email_clause, join_decider_clause, group_owner_clause = (
                self._dynamic_safety_clauses(cursor)
            )
            cursor.execute(
                f"""
                SELECT signup_request.id::text,
                       signup_request.user_id::text,
                       signup_request.status,
                       COALESCE(signup_request.decided_at, signup_request.updated_at)
                  FROM signup_requests AS signup_request
                  JOIN users AS signup_user
                    ON signup_user.id=signup_request.user_id
                 WHERE signup_request.status IN ('rejected', 'expired')
                   AND COALESCE(signup_request.decided_at, signup_request.updated_at) <= %s
                   AND signup_user.is_active=FALSE
                   AND NOT EXISTS (
                       SELECT 1
                         FROM signup_requests AS other_request
                        WHERE other_request.user_id=signup_user.id
                          AND other_request.id<>signup_request.id
                   )
                   AND NOT EXISTS (
                       SELECT 1
                         FROM user_group_map AS membership
                        WHERE membership.user_id=signup_user.id
                   )
                   AND NOT EXISTS (
                       SELECT 1
                         FROM join_requests AS join_request
                        WHERE join_request.user_id=signup_user.id{join_email_clause}
                   )
                   AND NOT EXISTS (
                       SELECT 1
                         FROM signup_requests AS decided_request
                        WHERE decided_request.decided_by_user_id=signup_user.id
                   )
                   AND NOT EXISTS (
                       SELECT 1
                         FROM signup_request_events AS actor_event
                        WHERE actor_event.actor_user_id=signup_user.id
                   )
                   {join_decider_clause}
                   {group_owner_clause}
                 ORDER BY COALESCE(signup_request.decided_at, signup_request.updated_at),
                          signup_request.id
                 LIMIT %s
                """,
                [cutoff, batch_size],
            )
            rows = cursor.fetchall()

        return tuple(
            SignupRetentionCandidate(
                signup_request_id=str(row[0]),
                user_id=str(row[1]),
                status=str(row[2]),
                retention_started_at=row[3],
            )
            for row in rows
        )

    def purge_candidate(self, candidate: SignupRetentionCandidate) -> None:
        # Dependency order is deliberate because signup schema FKs use RESTRICT.
        with connections[self.alias].cursor() as cursor:
            join_email_clause, join_decider_clause, group_owner_clause = (
                self._dynamic_safety_clauses(cursor)
            )
            cursor.execute(
                """
                SELECT signup_request.status,
                       COALESCE(signup_request.decided_at, signup_request.updated_at),
                       signup_user.is_active,
                       signup_user.email
                  FROM signup_requests AS signup_request
                  JOIN users AS signup_user ON signup_user.id=signup_request.user_id
                 WHERE signup_request.id=%s
                   AND signup_request.user_id=%s
                 FOR UPDATE OF signup_request, signup_user
                """,
                [candidate.signup_request_id, candidate.user_id],
            )
            row = cursor.fetchone()
            if (
                row is None
                or str(row[0]) not in TERMINAL_RETENTION_STATUSES
                or row[2] is not False
                or row[1] != candidate.retention_started_at
            ):
                raise RuntimeError("signup retention candidate changed before purge")

            cursor.execute(
                "DELETE FROM signup_verification_delivery_outbox WHERE signup_request_id=%s",
                [candidate.signup_request_id],
            )
            cursor.execute(
                "DELETE FROM signup_email_verification_tokens WHERE signup_request_id=%s",
                [candidate.signup_request_id],
            )
            cursor.execute(
                "DELETE FROM signup_request_events WHERE signup_request_id=%s",
                [candidate.signup_request_id],
            )
            cursor.execute(
                """
                DELETE FROM signup_requests
                 WHERE id=%s
                   AND user_id=%s
                   AND status IN ('rejected', 'expired')
                """,
                [candidate.signup_request_id, candidate.user_id],
            )
            if cursor.rowcount != 1:
                raise RuntimeError("signup retention candidate changed before purge")

            self._anonymize_django_session_bridge(
                cursor,
                email=str(row[3]),
            )
            self._delete_legacy_password_tokens(
                cursor,
                user_id=candidate.user_id,
            )
            cursor.execute(
                f"""
                DELETE FROM users AS signup_user
                 WHERE signup_user.id=%s
                   AND signup_user.is_active=FALSE
                   AND NOT EXISTS (
                       SELECT 1 FROM signup_requests AS remaining_request
                        WHERE remaining_request.user_id=signup_user.id
                   )
                   AND NOT EXISTS (
                       SELECT 1 FROM user_group_map AS membership
                        WHERE membership.user_id=signup_user.id
                   )
                   AND NOT EXISTS (
                       SELECT 1 FROM join_requests AS join_request
                        WHERE join_request.user_id=signup_user.id{join_email_clause}
                   )
                   AND NOT EXISTS (
                       SELECT 1 FROM signup_requests AS decided_request
                        WHERE decided_request.decided_by_user_id=signup_user.id
                   )
                   AND NOT EXISTS (
                       SELECT 1 FROM signup_request_events AS actor_event
                        WHERE actor_event.actor_user_id=signup_user.id
                   )
                   {join_decider_clause}
                   {group_owner_clause}
                """,
                [candidate.user_id],
            )
            if cursor.rowcount != 1:
                raise RuntimeError("inactive signup identity could not be purged safely")


def one_year_before(moment: datetime) -> datetime:
    """Return the calendar anniversary one year earlier, including leap-day handling."""

    if not isinstance(moment, datetime):
        raise ValueError("moment must be a datetime")
    try:
        return moment.replace(year=moment.year - 1)
    except ValueError:
        # February 29 -> February 28 in the previous non-leap year.
        return moment.replace(year=moment.year - 1, day=28)


def purge_terminal_signup_data(
    *,
    execute: bool = False,
    batch_size: int = 100,
    repository: SignupRetentionRepository | None = None,
    clock=timezone.now,
) -> SignupRetentionResult:
    """Purge one bounded batch of rejected/expired signup-only identities.

    The default is a non-writing dry run. Callers must explicitly set execute=True.
    No scheduler should enable execute mode before an operational approval.
    """

    if not 1 <= batch_size <= 500:
        raise ValueError("batch_size must be between 1 and 500")

    now = clock()
    cutoff = one_year_before(now)
    repository = repository or CentralSignupRetentionRepository()
    candidates = repository.list_candidates(cutoff=cutoff, batch_size=batch_size)

    if not execute:
        return SignupRetentionResult(
            candidates=len(candidates),
            purged=0,
            dry_run=True,
        )

    alias = getattr(
        repository,
        "alias",
        getattr(settings, "CENTRAL_DB_ALIAS", "default"),
    )
    purged = 0
    for candidate in candidates:
        with transaction.atomic(using=alias):
            repository.purge_candidate(candidate)
        purged += 1

    return SignupRetentionResult(
        candidates=len(candidates),
        purged=purged,
        dry_run=False,
    )
