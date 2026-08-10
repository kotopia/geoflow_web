from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import connections, transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from .account_password_reset_token_service import (
    AccountPasswordResetTokenRepository,
    CentralAccountPasswordResetTokenRepository,
    consume_account_password_reset_token,
)
from .central_login_authentication import (
    CentralLoginPasswordConfigurationError,
    verify_central_login_password,
)
from .signup_verification_token_service import HmacSha256VerificationKeyRing


MAX_PASSWORD_LENGTH = 128


class AccountPasswordResetError(RuntimeError):
    pass


class AccountPasswordResetRejected(AccountPasswordResetError):
    """Publicly safe reset rejection: invalid/expired token or invalid password."""


@dataclass(frozen=True)
class AccountPasswordResetResult:
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


@sensitive_variables("new_password", "encoded_password")
def _validate_new_password(*, email: str, encoded_password: str, new_password: str) -> None:
    if not new_password or len(new_password) > MAX_PASSWORD_LENGTH:
        raise AccountPasswordResetRejected("password policy rejected")

    try:
        reused = verify_central_login_password(new_password, encoded_password)
    except CentralLoginPasswordConfigurationError:
        raise AccountPasswordResetRejected("password policy rejected") from None
    if reused.valid:
        raise AccountPasswordResetRejected("password reuse rejected")

    validator_user = SimpleNamespace(
        username=email,
        email=email,
        first_name="",
        last_name="",
    )
    try:
        validate_password(new_password, user=validator_user)
    except ValidationError:
        raise AccountPasswordResetRejected("password policy rejected") from None


@sensitive_variables("token", "new_password", "new_hash", "key_ring")
def reset_account_password_with_token(
    *,
    token: str,
    new_password: str,
    key_ring: HmacSha256VerificationKeyRing,
    alias: str | None = None,
    token_repository: AccountPasswordResetTokenRepository | None = None,
) -> AccountPasswordResetResult:
    """Consume one reset capability and rotate central/bridge credentials atomically."""

    if not isinstance(token, str) or not token.strip():
        raise AccountPasswordResetRejected("password reset token rejected")
    resolved_alias = alias or getattr(settings, "CENTRAL_DB_ALIAS", "default")
    token_repository = token_repository or CentralAccountPasswordResetTokenRepository(
        resolved_alias
    )
    repository_alias = getattr(token_repository, "alias", resolved_alias)
    if repository_alias != resolved_alias:
        raise AccountPasswordResetError("password reset repository alias mismatch")

    bridge_rotated = False
    legacy_tokens_invalidated = False
    now = timezone.now()

    with transaction.atomic(using=resolved_alias):
        user_id = consume_account_password_reset_token(
            token.strip(),
            key_ring=key_ring,
            repository=token_repository,
            clock=lambda: now,
        )
        if user_id is None:
            raise AccountPasswordResetRejected("password reset token rejected")

        with connections[resolved_alias].cursor() as cursor:
            cursor.execute(
                """
                SELECT id::text, email, password_hash
                  FROM users
                 WHERE id=%s
                   AND is_active=TRUE
                   AND email_verified=TRUE
                 FOR UPDATE
                """,
                [user_id],
            )
            row = cursor.fetchone()
            if row is None:
                raise AccountPasswordResetRejected("password reset account rejected")
            locked_user_id, email, encoded_password = row
            _validate_new_password(
                email=str(email or "").strip().lower(),
                encoded_password=str(encoded_password or ""),
                new_password=new_password,
            )
            new_hash = make_password(new_password)
            cursor.execute(
                """
                UPDATE users
                   SET password_hash=%s, updated_at=now()
                 WHERE id=%s
                   AND is_active=TRUE
                   AND email_verified=TRUE
                """,
                [new_hash, locked_user_id],
            )
            if cursor.rowcount != 1:
                raise AccountPasswordResetError("central password update failed")

            cursor.execute(
                """
                UPDATE account_password_reset_tokens
                   SET revoked_at=GREATEST(%s, created_at)
                 WHERE user_id=%s
                   AND consumed_at IS NULL
                   AND revoked_at IS NULL
                """,
                [now, locked_user_id],
            )

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

        User = get_user_model()
        bridge_user = (
            User.objects.using(resolved_alias)
            .filter(username__iexact=str(email or "").strip())
            .first()
        )
        if bridge_user is not None:
            bridge_user.set_unusable_password()
            bridge_user.save(using=resolved_alias, update_fields=["password"])
            bridge_rotated = True

    return AccountPasswordResetResult(
        user_id=str(locked_user_id),
        bridge_session_hash_rotated=bridge_rotated,
        legacy_tokens_invalidated=legacy_tokens_invalidated,
    )
