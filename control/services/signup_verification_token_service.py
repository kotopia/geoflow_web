from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Mapping, Protocol

from django.conf import settings
from django.db import connections, transaction
from django.utils import timezone

from .signup_verification_service import EmailVerificationGrant

SIGNUP_EMAIL_VERIFICATION_PURPOSE = "signup_email_verification"
SIGNUP_EMAIL_VERIFICATION_DIGEST_ALGORITHM = "hmac_sha256"
SIGNUP_EMAIL_VERIFICATION_TOKEN_VERSION = "v1"
SIGNUP_EMAIL_VERIFICATION_RANDOM_BYTES = 32

_KEY_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{32,256}$")
_DIGEST_DOMAIN = b"geoflow.signup_email_verification.v1\x00"


class SignupEmailVerificationTokenIssuanceRejected(Exception):
    pass


@dataclass(frozen=True)
class IssuedSignupEmailVerificationToken:
    token: str
    expires_at: datetime


class SignupEmailVerificationTokenRepository(Protocol):
    def create_digest(self, **kwargs) -> bool: ...

    def consume_digest(self, **kwargs) -> EmailVerificationGrant | None: ...


class HmacSha256VerificationKeyRing:
    def __init__(self, *, active_key_id: str, keys: Mapping[str, bytes]):
        if not _KEY_ID_RE.fullmatch(active_key_id):
            raise ValueError("active digest key id is invalid")
        normalized: dict[str, bytes] = {}
        for key_id, key in keys.items():
            if not _KEY_ID_RE.fullmatch(key_id):
                raise ValueError("digest key id is invalid")
            if not isinstance(key, bytes) or len(key) < 32:
                raise ValueError("digest keys must contain at least 32 bytes")
            normalized[key_id] = key
        if active_key_id not in normalized:
            raise ValueError("active digest key id is not present in the key ring")
        self._active_key_id = active_key_id
        self._keys = normalized

    @property
    def active_key_id(self) -> str:
        return self._active_key_id

    def active_key(self) -> bytes:
        return self._keys[self._active_key_id]

    def key_for(self, key_id: str) -> bytes | None:
        return self._keys.get(key_id)


class CentralSignupEmailVerificationTokenRepository:
    def __init__(self, alias: str | None = None):
        self.alias = alias or getattr(settings, "CENTRAL_DB_ALIAS", "default")

    def create_digest(
        self,
        *,
        signup_request_id: str,
        purpose: str,
        token_digest: str,
        digest_algorithm: str,
        digest_key_id: str,
        expires_at,
        created_at,
    ) -> bool:
        with connections[self.alias].cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO signup_email_verification_tokens (
                    id, signup_request_id, purpose, token_digest,
                    digest_algorithm, digest_key_id, expires_at,
                    consumed_at, created_at
                )
                SELECT %s, signup_request.id, %s, %s, %s, %s, %s, NULL, %s
                  FROM signup_requests AS signup_request
                  JOIN users AS signup_user ON signup_user.id=signup_request.user_id
                 WHERE signup_request.id=%s
                   AND signup_request.status='pending_email_verification'
                   AND signup_user.email_verified=FALSE
                   AND signup_user.is_active=FALSE
                RETURNING id
                """,
                [
                    uuid.uuid4(),
                    purpose,
                    token_digest,
                    digest_algorithm,
                    digest_key_id,
                    expires_at,
                    created_at,
                    signup_request_id,
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
        consumed_at,
    ) -> EmailVerificationGrant | None:
        with connections[self.alias].cursor() as cursor:
            cursor.execute(
                """
                UPDATE signup_email_verification_tokens AS verification_token
                   SET consumed_at=%s
                  FROM signup_requests AS signup_request,
                       users AS signup_user
                 WHERE verification_token.signup_request_id=signup_request.id
                   AND signup_user.id=signup_request.user_id
                   AND verification_token.purpose=%s
                   AND verification_token.digest_algorithm=%s
                   AND verification_token.digest_key_id=%s
                   AND verification_token.token_digest=%s
                   AND verification_token.consumed_at IS NULL
                   AND verification_token.expires_at > %s
                   AND signup_request.status='pending_email_verification'
                   AND signup_user.email_verified=FALSE
                   AND signup_user.is_active=FALSE
                RETURNING signup_request.user_id, signup_request.id
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
        if row is None:
            return None
        return EmailVerificationGrant(
            user_id=str(row[0]), signup_request_id=str(row[1])
        )


class DatabaseSignupEmailVerificationTokenVerifier:
    def __init__(
        self,
        *,
        key_ring: HmacSha256VerificationKeyRing,
        repository: SignupEmailVerificationTokenRepository | None = None,
        clock: Callable[[], datetime] = timezone.now,
    ):
        self.key_ring = key_ring
        self.repository = repository or CentralSignupEmailVerificationTokenRepository()
        self.clock = clock

    def consume(self, token: str) -> EmailVerificationGrant | None:
        parsed = _parse_token(token)
        if parsed is None:
            return None
        key_id, _secret = parsed
        key = self.key_ring.key_for(key_id)
        if key is None:
            return None
        return self.repository.consume_digest(
            purpose=SIGNUP_EMAIL_VERIFICATION_PURPOSE,
            token_digest=_digest_token(key=key, token=token),
            digest_algorithm=SIGNUP_EMAIL_VERIFICATION_DIGEST_ALGORITHM,
            digest_key_id=key_id,
            consumed_at=self.clock(),
        )


def issue_signup_email_verification_token(
    *,
    signup_request_id: str,
    ttl: timedelta,
    key_ring: HmacSha256VerificationKeyRing,
    repository: SignupEmailVerificationTokenRepository | None = None,
    clock: Callable[[], datetime] = timezone.now,
    token_factory: Callable[[int], str] = secrets.token_urlsafe,
    atomic_context=None,
) -> IssuedSignupEmailVerificationToken:
    if ttl <= timedelta(0):
        raise ValueError("verification token ttl must be positive")

    repository = repository or CentralSignupEmailVerificationTokenRepository()
    default_alias = getattr(settings, "CENTRAL_DB_ALIAS", "default")
    alias = getattr(repository, "alias", default_alias)
    context = atomic_context or transaction.atomic(using=alias)

    created_at = clock()
    expires_at = created_at + ttl
    key_id = key_ring.active_key_id
    secret = token_factory(SIGNUP_EMAIL_VERIFICATION_RANDOM_BYTES)
    if not isinstance(secret, str) or not _SECRET_RE.fullmatch(secret):
        raise ValueError("token factory returned an invalid URL-safe secret")

    token = f"{SIGNUP_EMAIL_VERIFICATION_TOKEN_VERSION}.{key_id}.{secret}"
    digest = _digest_token(key=key_ring.active_key(), token=token)
    with context:
        created = repository.create_digest(
            signup_request_id=signup_request_id,
            purpose=SIGNUP_EMAIL_VERIFICATION_PURPOSE,
            token_digest=digest,
            digest_algorithm=SIGNUP_EMAIL_VERIFICATION_DIGEST_ALGORITHM,
            digest_key_id=key_id,
            expires_at=expires_at,
            created_at=created_at,
        )
        if not created:
            raise SignupEmailVerificationTokenIssuanceRejected(
                "verification token could not be issued"
            )
    return IssuedSignupEmailVerificationToken(token=token, expires_at=expires_at)


def _parse_token(token: str) -> tuple[str, str] | None:
    if not isinstance(token, str):
        return None
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != SIGNUP_EMAIL_VERIFICATION_TOKEN_VERSION:
        return None
    key_id, secret = parts[1], parts[2]
    if not _KEY_ID_RE.fullmatch(key_id) or not _SECRET_RE.fullmatch(secret):
        return None
    return key_id, secret


def _digest_token(*, key: bytes, token: str) -> str:
    return hmac.new(
        key, _DIGEST_DOMAIN + token.encode("ascii"), hashlib.sha256
    ).hexdigest()
