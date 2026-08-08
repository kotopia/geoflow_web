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

    def _join_request_email_column(self, cursor) -> str | None:
        if self._column_exists(cursor, "join_requests", "email"):
            return "email"
        if self._column_exists(cursor, "join_requests", "requested_email"):
            return "requested_email"
        return None

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

    def _has_external_audit_reference(self, cursor, *, user_id: str) -> bool:
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

        if self._column_exists(cursor, "join_requests", "decided_by"):
            cursor.execute(
                """
                SELECT 1
                  FROM join_requests
                 WHERE decided_by=%s
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

            # Group ownership is a business authority, not merely a login artifact.
            # Require explicit transfer instead of silently orphaning the group.
            self._require_no_group_ownership(cursor, user_id=user_id)

            cursor.execute(
                "SELECT id::text FROM signup_requests WHERE user_id=%s",
                [user_id],
            )
            own_request_ids = tuple(str(value[0]) for value in cursor.fetchall())

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
            join_email_column = self._join_request_email_column(cursor)
            if join_email_column is None:
                cursor.execute("DELETE FROM join_requests WHERE user_id=%s", [user_id])
            else:
                cursor.execute(
                    f"DELETE FROM join_requests WHERE user_id=%s OR lower({join_email_column})=lower(%s)",
                    [user_id, email],
                )
            cursor.execute("DELETE FROM password_reset_tokens WHERE user_id=%s", [user_id])

            if self._has_external_audit_reference(cursor, user_id=user_id):
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
