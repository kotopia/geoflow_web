from __future__ import annotations

import uuid
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Literal, Protocol

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import IntegrityError, connections, transaction
from django.utils import timezone


class AccountErasureError(Exception):
    """Raised when central account erasure cannot be completed safely."""


@dataclass(frozen=True)
class AccountErasureResult:
    mode: Literal["deleted", "anonymized"]


class CentralAccountErasureRepository(Protocol):
    alias: str

    def erase(self, *, user_id: str, unusable_password_hash: str) -> AccountErasureResult: ...


class SqlCentralAccountErasureRepository:
    """Erase central identity data while preserving unrelated audit FK integrity.

    The service owns only central identity/account artifacts. It deliberately does not
    delete tenant operational or personnel records. A central user that still owns a
    group must have that ownership reassigned before erasure. If another central table
    unexpectedly retains a foreign-key reference, hard deletion falls back to irreversible
    anonymization so the account cannot authenticate and identifying account fields are
    removed while referential integrity remains intact.
    """

    def __init__(self, alias: str | None = None):
        self.alias = alias or getattr(settings, "CENTRAL_DB_ALIAS", "default")

    _SIGNUP_TABLES = (
        "signup_requests",
        "signup_request_events",
        "signup_email_verification_tokens",
        "signup_verification_delivery_outbox",
    )

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

    def _signup_schema_mode(self, cursor) -> Literal["absent", "complete"]:
        presence = {
            table: self._table_exists(cursor, table)
            for table in self._SIGNUP_TABLES
        }
        if all(presence.values()):
            return "complete"
        if not any(presence.values()):
            return "absent"
        raise AccountErasureError(
            "signup schema is partially installed; account erasure is blocked"
        )

    def _join_request_email_columns(self, cursor) -> tuple[str, ...]:
        return tuple(
            column
            for column in ("requested_email", "email")
            if self._column_exists(cursor, "join_requests", column)
        )

    def _join_request_decider_columns(self, cursor) -> tuple[str, ...]:
        return tuple(
            column
            for column in ("decided_by", "decided_by_user_id")
            if self._column_exists(cursor, "join_requests", column)
        )

    def _delete_join_requests_for_identity(
        self,
        cursor,
        *,
        user_id: str,
        email: str,
    ) -> None:
        conditions = ["user_id=%s"]
        params: list[str] = [user_id]
        for column in self._join_request_email_columns(cursor):
            conditions.append(f"lower({column})=lower(%s)")
            params.append(email)
        cursor.execute(
            "DELETE FROM join_requests WHERE " + " OR ".join(conditions),
            params,
        )

    def _delete_legacy_password_tokens(self, cursor, *, user_id: str) -> None:
        for table in ("password_reset_tokens", "user_tokens"):
            if self._table_exists(cursor, table):
                cursor.execute(f"DELETE FROM {table} WHERE user_id=%s", [user_id])

    def _anonymize_django_session_bridge(
        self,
        cursor,
        *,
        email: str,
        unusable_password_hash: str,
    ) -> int:
        """Remove central-account PII from Django's auth_user session bridge.

        The authoritative bridge key created by GeoFlow login is username=email.
        Fully de-privilege only those rows. For any other legacy Django row that
        merely carries the same email field, clear that email without changing
        unrelated credentials or privileges.
        """

        if not self._table_exists(cursor, "auth_user"):
            return 0
        cursor.execute(
            """
            SELECT id
              FROM auth_user
             WHERE lower(COALESCE(username, ''))=lower(%s)
             FOR UPDATE
            """,
            [email],
        )
        bridge_ids = tuple(row[0] for row in cursor.fetchall())
        for bridge_id in bridge_ids:
            erased_username = f"erased-session-{uuid.uuid4()}@example.invalid"
            cursor.execute(
                """
                UPDATE auth_user
                   SET username=%s,
                       email='',
                       password=%s,
                       first_name='',
                       last_name='',
                       is_active=FALSE,
                       is_staff=FALSE,
                       is_superuser=FALSE,
                       last_login=NULL
                 WHERE id=%s
                """,
                [erased_username, unusable_password_hash, bridge_id],
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
        return len(bridge_ids)

    def _require_no_group_ownership(self, cursor, *, user_id: str) -> None:
        if not self._column_exists(cursor, "groups", "owner_user_id"):
            return
        cursor.execute(
            "SELECT 1 FROM groups WHERE owner_user_id=%s LIMIT 1",
            [user_id],
        )
        if cursor.fetchone() is not None:
            raise AccountErasureError(
                "central account owns a group; transfer ownership before erasure"
            )

    def _has_external_audit_reference(
        self,
        cursor,
        *,
        user_id: str,
        signup_schema_mode: Literal["absent", "complete"],
    ) -> bool:
        preserve = False
        if signup_schema_mode == "complete":
            cursor.execute(
                """
                SELECT (
                    EXISTS(
                        SELECT 1 FROM signup_requests
                         WHERE decided_by_user_id=%s AND user_id<>%s
                    )
                    OR EXISTS(
                        SELECT 1
                          FROM signup_request_events AS event
                          JOIN signup_requests AS request
                            ON request.id=event.signup_request_id
                         WHERE event.actor_user_id=%s
                           AND request.user_id<>%s
                    )
                )
                """,
                [user_id, user_id, user_id, user_id],
            )
            preserve = bool(cursor.fetchone()[0])

        for decider_column in self._join_request_decider_columns(cursor):
            cursor.execute(
                f"""
                SELECT 1
                  FROM join_requests
                 WHERE {decider_column}=%s
                   AND COALESCE(user_id::text, '')<>%s
                 LIMIT 1
                """,
                [user_id, user_id],
            )
            preserve = preserve or cursor.fetchone() is not None
        return preserve

    def _anonymize(
        self,
        cursor,
        *,
        user_id: str,
        unusable_password_hash: str,
    ) -> AccountErasureResult:
        erased_email = f"erased-{uuid.uuid4()}@example.invalid"
        cursor.execute(
            """
            UPDATE users
               SET email=%s,
                   password_hash=%s,
                   name_display=NULL,
                   is_active=FALSE,
                   email_verified=FALSE,
                   is_staff=FALSE,
                   mfa_enabled=FALSE,
                   last_login=NULL,
                   updated_at=%s
             WHERE id=%s
            """,
            [erased_email, unusable_password_hash, timezone.now(), user_id],
        )
        if cursor.rowcount != 1:
            raise AccountErasureError("central account anonymization failed")
        return AccountErasureResult(mode="anonymized")

    def erase(self, *, user_id: str, unusable_password_hash: str) -> AccountErasureResult:
        with connections[self.alias].cursor() as cursor:
            cursor.execute(
                "SELECT email FROM users WHERE id=%s FOR UPDATE",
                [user_id],
            )
            row = cursor.fetchone()
            if row is None:
                raise AccountErasureError("central account does not exist")
            email = str(row[0])

            self._anonymize_django_session_bridge(
                cursor,
                email=email,
                unusable_password_hash=unusable_password_hash,
            )

            # Group ownership is a business authority, not merely a login artifact.
            # Require explicit transfer instead of silently orphaning the group.
            self._require_no_group_ownership(cursor, user_id=user_id)

            # Code may be deployed before the Phase 1 signup migrations are applied.
            # Treat a fully absent signup schema as legacy-compatible, but block a
            # partially installed schema because dependency cleanup would be unsafe.
            signup_schema_mode = self._signup_schema_mode(cursor)
            own_request_ids: tuple[str, ...] = ()
            if signup_schema_mode == "complete":
                cursor.execute(
                    "SELECT id::text FROM signup_requests WHERE user_id=%s",
                    [user_id],
                )
                own_request_ids = tuple(
                    str(value[0]) for value in cursor.fetchall()
                )

            if own_request_ids:
                cursor.execute(
                    "DELETE FROM signup_verification_delivery_outbox WHERE signup_request_id = ANY(%s::uuid[])",
                    [list(own_request_ids)],
                )
                cursor.execute(
                    "DELETE FROM signup_email_verification_tokens WHERE signup_request_id = ANY(%s::uuid[])",
                    [list(own_request_ids)],
                )
                cursor.execute(
                    "DELETE FROM signup_request_events WHERE signup_request_id = ANY(%s::uuid[])",
                    [list(own_request_ids)],
                )
                cursor.execute(
                    "DELETE FROM signup_requests WHERE id = ANY(%s::uuid[])",
                    [list(own_request_ids)],
                )

            cursor.execute("DELETE FROM user_group_map WHERE user_id=%s", [user_id])
            self._delete_join_requests_for_identity(
                cursor,
                user_id=user_id,
                email=email,
            )
            self._delete_legacy_password_tokens(cursor, user_id=user_id)

            if self._has_external_audit_reference(
                cursor,
                user_id=user_id,
                signup_schema_mode=signup_schema_mode,
            ):
                return self._anonymize(
                    cursor,
                    user_id=user_id,
                    unusable_password_hash=unusable_password_hash,
                )

        # A savepoint allows unexpected central FK references to fall back safely
        # without leaving the outer erasure transaction in a broken state.
        try:
            with transaction.atomic(using=self.alias):
                with connections[self.alias].cursor() as cursor:
                    cursor.execute("DELETE FROM users WHERE id=%s", [user_id])
                    if cursor.rowcount != 1:
                        raise AccountErasureError("central account deletion failed")
            return AccountErasureResult(mode="deleted")
        except IntegrityError:
            with connections[self.alias].cursor() as cursor:
                return self._anonymize(
                    cursor,
                    user_id=user_id,
                    unusable_password_hash=unusable_password_hash,
                )


def erase_central_account_personal_data(
    user_id: str,
    *,
    repository: CentralAccountErasureRepository | None = None,
    atomic_context: AbstractContextManager | None = None,
) -> AccountErasureResult:
    normalized_user_id = str(user_id).strip()
    if not normalized_user_id:
        raise ValueError("user_id is required")

    repository = repository or SqlCentralAccountErasureRepository()
    alias = getattr(repository, "alias", getattr(settings, "CENTRAL_DB_ALIAS", "default"))
    context = atomic_context or transaction.atomic(using=alias)
    unusable_password_hash = make_password(None)

    with context:
        return repository.erase(
            user_id=normalized_user_id,
            unusable_password_hash=unusable_password_hash,
        )
