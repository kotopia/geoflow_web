from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Protocol

from django.conf import settings
from django.db import connections, transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from .signup_verification_token_service import HmacSha256VerificationKeyRing


ACCOUNT_PASSWORD_RESET_PURPOSE = "account_password_reset"
ACCOUNT_PASSWORD_RESET_DIGEST_ALGORITHM = "hmac_sha256"
ACCOUNT_PASSWORD_RESET_TOKEN_VERSION = "pr1"
ACCOUNT_PASSWORD_RESET_RANDOM_BYTES = 32

_KEY_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{32,256}$")
_DIGEST_DOMAIN = b"geoflow.account_password_reset.v1\x00"


class AccountPasswordResetTokenIssuanceRejected(RuntimeError):
    pass


@dataclass(frozen=True)
class IssuedAccountPasswordResetToken:
    token: str = field(repr=False)
    expires_at: datetime


class AccountPasswordResetTokenRepository(Protocol):
    alias: str

    def revoke_unconsumed(self, **kwargs) -> int: ...

    def create_digest(self, **kwargs) -> bool: ...

    def consume_digest(self, **kwargs) -> str | None: ...


class CentralAccountPasswordResetTokenRepository:
    def __init__(self, alias: str | None = None):
        self.alias = alias or getattr(settings, "CENTRAL_DB_ALIAS", "default")

    def revoke_unconsumed(
        self,
        *,
        user_id: str,
        purpose: str,
        revoked_at: datetime,
    ) -> int:
        with connections[self.alias].cursor() as cursor:
            cursor.execute(
                """
                UPDATE account_password_reset_tokens
                   SET revoked_at=GREATEST(%s, created_at)
                 WHERE user_id=%s
                   AND purpose=%s
                   AND consumed_at IS NULL
                   AND revoked_at IS NULL
                """,
                [revoked_at, user_id, purpose],
            )
            return cursor.rowcount

    def create_digest(
        self,
        *,
        user_id: str,
        purpose: str,
        token_digest: str,
        digest_algorithm: str,
        digest_key_id: str,
        expires_at: datetime,
        created_at: datetime,
    ) -> bool:
        with connections[self.alias].cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO account_password_reset_tokens (
                    id, user_id, purpose, token_digest, digest_algorithm,
                    digest_key_id, expires_at, consumed_at, revoked_at, created_at
                )
                SELECT %s, account_user.id, %s, %s, %s, %s, %s,
                       NULL, NULL, %s
                  FROM users AS account_user
                 WHERE account_user.id=%s
                   AND account_user.is_active=TRUE
                   AND account_user.email_verified=TRUE
                   AND account_user.password_hash IS NOT NULL
                   AND length(trim(account_user.password_hash)) > 0
                ON CONFLICT DO NOTHING
                RETURNING id
                """,
                [
                    str(uuid.uuid4()),
                    purpose,
                    token_digest,
                    digest_algorithm,
                    digest_key_id,
                    expires_at,
                    created_at,
                    user_id,
                ],
            )
            return cursor.fetchone() is not None

    def consume_digest(
        self,
        *,
        purpose: str,
        token_digest: str,
        digest_algorithm: str,
        digest_key_id: str,
        consumed_at: datetime,
    ) -> str | None:
        with connections[self.alias].cursor() as cursor:
            cursor.execute(
                """
                UPDATE account_password_reset_tokens AS reset_token
                   SET consumed_at=%s
                  FROM users AS account_user
                 WHERE account_user.id=reset_token.user_id
                   AND reset_token.purpose=%s
                   AND reset_token.digest_algorithm=%s
                   AND reset_token.digest_key_id=%s
                   AND reset_token.token_digest=%s
                   AND reset_token.consumed_at IS NULL
                   AND reset_token.revoked_at IS NULL
                   AND reset_token.expires_at > %s
                   AND account_user.is_active=TRUE
                   AND account_user.email_verified=TRUE
                RETURNING reset_token.user_id
                """,
                [
                    consumed_at,
                    purpose,
                    digest_algorithm,
                    digest_key_id,
                    token_digest,
                    consumed_at,
                ],
            )
            row = cursor.fetchone()
        return str(row[0]) if row is not None else None


@sensitive_variables("token", "key_ring")
def consume_account_password_reset_token(
    token: str,
    *,
    key_ring: HmacSha256VerificationKeyRing,
    repository: AccountPasswordResetTokenRepository | None = None,
    clock: Callable[[], datetime] = timezone.now,
) -> str | None:
    parsed = _parse_token(token)
    if parsed is None:
        return None
    key_id, _secret = parsed
    key = key_ring.key_for(key_id)
    if key is None:
        return None
    repository = repository or CentralAccountPasswordResetTokenRepository()
    return repository.consume_digest(
        purpose=ACCOUNT_PASSWORD_RESET_PURPOSE,
        token_digest=_digest_token(key=key, token=token),
        digest_algorithm=ACCOUNT_PASSWORD_RESET_DIGEST_ALGORITHM,
        digest_key_id=key_id,
        consumed_at=clock(),
    )


@sensitive_variables("key_ring", "secret", "token")
def issue_account_password_reset_token(
    *,
    user_id: str,
    ttl: timedelta,
    key_ring: HmacSha256VerificationKeyRing,
    repository: AccountPasswordResetTokenRepository | None = None,
    clock: Callable[[], datetime] = timezone.now,
    token_factory: Callable[[int], str] = secrets.token_urlsafe,
    atomic_context=None,
) -> IssuedAccountPasswordResetToken:
    normalized_user_id = str(user_id or "").strip()
    if not normalized_user_id:
        raise ValueError("user_id is required")
    if ttl <= timedelta(0):
        raise ValueError("password reset token ttl must be positive")

    repository = repository or CentralAccountPasswordResetTokenRepository()
    alias = getattr(repository, "alias", getattr(settings, "CENTRAL_DB_ALIAS", "default"))
    context = atomic_context or transaction.atomic(using=alias)
    created_at = clock()
    expires_at = created_at + ttl
    key_id = key_ring.active_key_id
    secret = token_factory(ACCOUNT_PASSWORD_RESET_RANDOM_BYTES)
    if not isinstance(secret, str) or not _SECRET_RE.fullmatch(secret):
        raise ValueError("token factory returned an invalid URL-safe secret")
    if not _KEY_ID_RE.fullmatch(key_id):
        raise ValueError("active digest key id is invalid")

    token = f"{ACCOUNT_PASSWORD_RESET_TOKEN_VERSION}.{key_id}.{secret}"
    digest = _digest_token(key=key_ring.active_key(), token=token)
    with context:
        repository.revoke_unconsumed(
            user_id=normalized_user_id,
            purpose=ACCOUNT_PASSWORD_RESET_PURPOSE,
            revoked_at=created_at,
        )
        created = repository.create_digest(
            user_id=normalized_user_id,
            purpose=ACCOUNT_PASSWORD_RESET_PURPOSE,
            token_digest=digest,
            digest_algorithm=ACCOUNT_PASSWORD_RESET_DIGEST_ALGORITHM,
            digest_key_id=key_id,
            expires_at=expires_at,
            created_at=created_at,
        )
        if not created:
            raise AccountPasswordResetTokenIssuanceRejected(
                "password reset token could not be issued"
            )
    return IssuedAccountPasswordResetToken(token=token, expires_at=expires_at)


def _parse_token(token: str) -> tuple[str, str] | None:
    if not isinstance(token, str):
        return None
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != ACCOUNT_PASSWORD_RESET_TOKEN_VERSION:
        return None
    key_id, secret = parts[1], parts[2]
    if not _KEY_ID_RE.fullmatch(key_id) or not _SECRET_RE.fullmatch(secret):
        return None
    return key_id, secret


def _digest_token(*, key: bytes, token: str) -> str:
    return hmac.new(
        key,
        _DIGEST_DOMAIN + token.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
