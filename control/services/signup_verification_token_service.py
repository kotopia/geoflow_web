from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid
from contextlib import AbstractContextManager
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

_TOKEN_KEY_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_TOKEN_SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{32,256}$")
_DIGEST_DOMAIN = b"geoflow.signup_email_verification.v1\x00"


class SignupEmailVerificationTokenIssuanceRejected(Exception):
    """Fail-closed internal error for a stale or ineligible signup request."""


@dataclass(frozen=True)
class IssuedSignupEmailVerificationToken:
    """Raw token returned once to the delivery boundary; it must never be persisted."""

    token: str
    expires_at: datetime


class SignupEmailVerificationTokenRepository(Protocol):
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
    ) -> bool: ...

    def consume_digest(
        self,
        *,
        purpose: str,
        token_digest: str,
        digest_algorithm: str,
        digest_key_id: str,
        consumed_at,
    ) -> EmailVerificationGrant | None: ...


class HmacSha256VerificationKeyRing:
    """Injected HMAC key ring supporting one active key and bounded old-key rotation."""

    def __init__(self, *, active_key_id: str, keys: Mapping[str, bytes]):
        if not _TOKEN_KEY_ID_RE.fullmatch(active_key_id):
            raise ValueError("active digest key id is invalid")

        normalized: dict[str, bytes] = {}
        for key_id, key in keys.items():
            if not _TOKEN_KEY_ID_RE.fullmatch(key_id):
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
    """Central-DB persistence for digest-only, expiring, single-use verification tokens."""

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
            user_id=str(row[0]),
            signup_request_id=str(row[1]),
        )


class DatabaseSignupEmailVerificationTokenVerifier:
    """Concrete verifier compatible with signup_verification_service's protocol."""

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

        consumed_at = self.clock()
        return self.repository.consume_digest(
            purpose=SIGNUP_EMAIL_VERIFICATION_PURPOSE,
            token_digest=_digest_token(key=key, token=token),
            digest_algorithm=SIGNUP_EMAIL_VERIFICATION_DIGEST_ALGORITHM,
            digest_key_id=key_id,
            consumed_at=consumed_at,
        )


def issue_signup_email_verification_token(
    *,
    signup_request_id: str,
    ttl: timedelta,
    key_ring: HmacSha256VerificationKeyRing,
    repository: SignupEmailVerificationTokenRepository | None = None,
    clock: Callable[[], datetime] = timezone.now,
    token_factory: Callable[[int], str] = secrets.token_urlsafe,
    atomic_context: AbstractContextManager | None = None,
) -> IssuedSignupEmailVerificationToken:
    """Persist only a keyed digest and return the raw token once for later delivery."""

    if ttl <= timedelta(0):
        raise ValueError("verification token ttl must be positive")

    repository = repository or CentralSignupEmailVerificationTokenRepository()
    alias = getattr(repository, "alias", getattr(settings, "CENTRAL_DB_ALIAS", "default"))
    context = atomic_context or transaction.atomhÊ\Ú[™ÏX[X\ÊB‚ˆÜ™X]YØ]HÛØÚÊ
Bˆ^\™\×Ø]HÜ™X]YØ]
ÈˆÙ^WÚYHÙ^WÜš[™Ë˜XÝ]™WÚÙ^WÚYˆÙXÜ™]HÚÙ[—Ù˜XÝÜžJÒQÓ•TÑSPRSÕ‘T’Q’PÐUSÓ—ÔS‘ÓWÐ–UTÊBˆYˆ›Ý\Ú[œÝ[˜ÙJÙXÜ™]ÝŠHÜˆ›ÝÕÒÑS—ÔÑPÔ‘UÔ‘K™[X]Ú
ÙXÜ™]
N‚ˆ˜Z\ÙH˜[YQ\œ›ÜŠÚÙ[ˆ˜XÝÜžH™]\›™Y[ˆ[˜[YT“\ØY™HÙXÜ™]ŠB‚ˆÚÙ[ˆHˆžÔÒQÓ•TÑSPRSÕ‘T’Q’PÐUSÓ—ÕÒÑS—Õ‘T”ÒSÓŸKžÚÙ^WÚYKžÜÙXÜ™]H‚ˆÚÙ[—ÙYÙ\ÝHÙYÙ\ÝÝÚÙ[ŠÙ^OZÙ^WÜš[™Ë˜XÝ]™WÚÙ^J
KÚÙ[]ÚÙ[ŠB‚ˆÚ]ÛÛ^‚ˆÜ™X]YH™\ÜÚ]ÜžK˜Ü™X]WÙYÙ\Ý
ˆÚYÛ\Ü™\]Y\ÝÚY\ÚYÛ\Ü™\]Y\ÝÚYˆ\œÜÙOTÒQÓ•TÑSPRSÕ‘T’Q’PÐUSÓ—ÔT”ÔÑKˆÚÙ[—ÙYÙ\Ý]ÚÙ[—ÙYÙ\ÝˆYÙ\ÝØ[ÛÜš]OTÒQÓ•TÑSPRSÕ‘T’Q’PÐUSÓ—ÑQÑTÕÐSÓÔ’UKˆYÙ\ÝÚÙ^WÚYZÙ^WÚYˆ^\™\×Ø]Y^\™\×Ø]ˆÜ™X]YØ]XÜ™X]YØ]ˆ
BˆYˆ›ÝÜ™X]Y‚ˆ˜Z\ÙHÚYÛ\[XZ[™\šYšXØ][Û•ÚÙ[’\ÜÝX[˜ÙT™Z™XÝY
ˆ™\šYšXØ][ÛˆÚÙ[ˆÛÝ[›Ý™H\ÜÝYY‚ˆ
B‚ˆ™]\›ˆ\ÜÝYYÚYÛ\[XZ[™\šYšXØ][Û•ÚÙ[ŠÚÙ[]ÚÙ[‹^\™\×Ø]Y^\™\×Ø]
B‚‚™YˆÜ\œÙWÝÚÙ[ŠÚÙ[ŽˆÝŠHOˆ\VÜÝ‹Ý—H›Û™N‚ˆYˆ›Ý\Ú[œÝ[˜ÙJÚÙ[‹ÝŠN‚ˆ™]\›ˆ›Û™B‚ˆ\ÈHÚÙ[‹œÜ]
‹ˆŠBˆYˆ[Š\ÊHOHÈÜˆ\ÖÌHOHÒQÓ•TÑSPRSÕ‘T’Q’PÐUSÓ—ÕÒÑS—Õ‘T”ÒSÓŽ‚ˆ™]\›ˆ›Û™B‚ˆÙ^WÚYÙXÜ™]H\ÖÌWK\ÖÌ—BˆYˆ›ÝÕÒÑS—ÒÑVWÒQÔ‘K™[X]Ú
Ù^WÚY
N‚ˆ™]\›ˆ›Û™BˆYˆ›Ý\Ú[œÝ[˜ÙJÙXÜ™]ÝŠHÜˆ›ÝÕÒÑS—ÔÑPÔ‘UÔ‘K™[X]Ú
ÙXÜ™]
N‚ˆ™]\›ˆ›Û™Bˆ™]\›ˆÙ^WÚYÙXÜ™]‚‚™YˆÙYÙ\ÝÝÚÙ[Š
‹Ù^Nˆž]\ËÚÙ[ŽˆÝŠHOˆÝŽ‚ˆ™]\›ˆXXË›™]ÊˆÙ^KˆÑQÑTÕÑÓPRSˆ
ÈÚÙ[‹™[˜ÛÙJ˜\ØÚZHŠKˆ\ÚX‹œÚLM‹ˆ
Kš^YÙ\Ý

B