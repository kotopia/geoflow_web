from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import connections, transaction
from django.views.decorators.debug import sensitive_variables

from .central_login_authentication import (
    CentralLoginPasswordConfigurationError,
    verify_central_login_password,
)


MAX_PASSWORD_LENGTH = 128


class CentralPasswordChangeError(RuntimeError):
    """Base error for authenticated central password changes."""


class CentralPasswordChangeAuthenticationError(CentralPasswordChangeError):
    """The current central password could not be verified."""


class CentralPasswordChangeValidationError(CentralPasswordChangeError):
    """The requested new password does not satisfy the account policy."""


@dataclass(frozen=True)
class CentralPasswordChangeResult:
    user_id: str
    bridge_session_hash_rotated: bool
    legacy_tokens_invalidated: bool


def _table_exists(cursor, table_name: str) -> bool:
    cursor.execute(
        """
        SELECT 1
          FROM information_schema.tables
         WHERE table_schema='public'
           AND table_name=%s
         LIMIT 1
        """,
        [table_name],
    )
    return cursor.fetchone() is not None


@sensitive_variables("current_password", "new_password", "encoded_password")
def _validate_password_change(
    *,
    email: str,
    encoded_password: str,
    current_password: str,
    new_password: str,
) -> None:
    if not current_password or not new_password or len(new_password) > MAX_PASSWORD_LENGTH:
        raise CentralPasswordChangeValidationError("password policy rejected")

    try:
        current_result = verify_central_login_password(
            current_password,
            encoded_password,
        )
    except CentralLoginPasswordConfigurationError as exc:
        raise CentralPasswordChangeAuthenticationError(
            "current password verification unavailable"
        ) from exc
    if not current_result.valid:
        raise CentralPasswordChangeAuthenticationError("current password rejected")

    try:
        reused_result = verify_central_login_password(new_password, encoded_password)
    except CentralLoginPasswordConfigurationError as exc:
        raise CentralPasswordChangeValidationError(
            "new password comparison unavailable"
        ) from exc
    if reused_result.valid:
        raise CentralPasswordChangeValidationError("new password must differ")

    validator_user = SimpleNamespace(
        username=email,
        email=email,
        first_name="",
        last_name="",
    )
    try:
        validate_password(new_password, user=validator_user)
    except ValidationError as exc:
        raise CentralPasswordChangeValidationError("password policy rejected") from exc


@sensitive_variables(
    "current_password",
    "new_password",
    "encoded_password",
    "new_hash",
)
def change_authenticated_central_password(
    *,
    user_id: str,
    current_password: str,
    new_password: str,
) -> CentralPasswordChangeResult:
    """Change an active verified central user's password and invalidate bridge sessions.

    The central user row is locked for the current-password check and hash update.
    Legacy reset/setup tokens, when that compatibility table exists, are consumed.
    The authenticated Django bridge account must exist and receives a fresh unusable
    password so sessions authenticated with its previous auth hash become invalid.
    """

    normalized_user_id = str(user_id or "").strip()
    if not normalized_user_id:
        raise CentralPasswordChangeAuthenticationError("central identity unavailable")

    central_alias = getattr(settings, "CENTRAL_DB_ALIAS", "default")
    legacy_tokens_invalidated = False

    with transaction.atomic(using=central_alias):
        with connections[central_alias].cursor() as cursor:
            cursor.execute(
                """
                SELECT id::text, email, password_hash
                  FROM users
                 WHERE id=%s
                   AND is_active=TRUE
                   AND email_verified=TRUE
                 FOR UPDATE
                """,
                [normalized_user_id],
            )
            row = cursor.fetchone()
            if not row:
                raise CentralPasswordChangeAuthenticationError(
                    "active verified central account unavailable"
                )

            locked_user_id, email, encoded_password = row
            normalized_email = str(email or "").strip().lower()
            _validate_password_change(
                email=normalized_email,
                encoded_password=str(encoded_password or ""),
                current_password=current_password,
                new_password=new_password,
            )

            User = get_user_model()
            bridge_user = (
                User.objects.using(central_alias)
                .filter(username__iexact=normalized_email)
                .first()
            )
            if bridge_user is None:
                raise CentralPasswordChangeError(
                    "authenticated bridge account unavailable"
                )

            new_hash = make_password(new_password)
            cursor.execute(
                """
                UPDATE users
                   SET password_hash=%s,
                       updated_at=now()
                 WHERE id=%s
                   AND is_active=TRUE
                   AND email_verified=TRUE
                """,
                [new_hash, locked_user_id],
            )
            if cursor.rowcount != 1:
                raise CentralPasswordChangeError("central password update failed")

            if _table_exists(cursor, "password_reset_tokens"):
                cursor.execute(
                    """
                    UPDATE password_reset_tokens
                       SET used=TRUE
                     WHERE user_id=%s
                       AND used=FALSE
                    """,
                    [locked_user_id],
                )
                legacy_tokens_invalidated = True

            bridge_user.set_unusable_password()
            bridge_user.save(using=central_alias, update_fields=["password"])

    return CentralPasswordChangeResult(
        user_id=str(locked_user_id),
        bridge_session_hash_rotated=True,
        legacy_tokens_invalidated=legacy_tokens_invalidated,
    )
