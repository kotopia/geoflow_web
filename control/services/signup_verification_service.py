from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol

from django.conf import settings
from django.db import connections, transaction
from django.utils import timezone


PUBLIC_VERIFICATION_ERROR = "이메일 인증 요청을 처리할 수 없습니다. 새 인증 안내를 요청해 주세요."


class EmailVerificationRejected(Exception):
    """Fail-closed public error for invalid, expired, replayed, or stale verification."""


class EmailVerificationConfigurationError(RuntimeError):
    """Internal error for cross-database verification configuration."""


@dataclass(frozen=True)
class EmailVerificationGrant:
    """Non-secret identity returned after an email-verification token is consumed."""

    user_id: str
    signup_request_id: str


class EmailVerificationTokenVerifier(Protocol):
    def consume(self, token: str) -> EmailVerificationGrant | None:
        """Validate and consume once in the caller's central transaction.

        Implementations must bind the token to the email-verification purpose, enforce
        expiry and replay protection, and never persist or return the raw token.
        """


class SignupVerificationRepository(Protocol):
    def transition_request_to_pending_approval(
        self, *, signup_request_id: str, user_id: str, changed_at
    ) -> bool: ...

    def mark_email_verified(self, *, user_id: str, changed_at) -> bool: ...

    def append_verified_event(
        self, *, signup_request_id: str, created_at
    ) -> None: ...


class CentralSignupVerificationRepository:
    def __init__(self, alias: str | None = None):
        self.alias = alias or getattr(settings, "CENTRAL_DB_ALIAS", "default")

    def transition_request_to_pending_approval(
        self, *, signup_request_id: str, user_id: str, changed_at
    ) -> bool:
        with connections[self.alias].cursor() as cursor:
            cursor.execute(
                """
                UPDATE signup_requests
                   SET status='pending_approval', version=version + 1, updated_at=%s
                 WHERE id=%s AND user_id=%s
                   AND status='pending_email_verification'
                """,
                [changed_at, signup_request_id, user_id],
            )
            return cursor.rowcount == 1

    def mark_email_verified(self, *, user_id: str, changed_at) -> bool:
        with connections[self.alias].cursor() as cursor:
            cursor.execute(
                """
                UPDATE users
                   SET email_verified=TRUE, updated_at=%s
                 WHERE id=%s AND is_active=FALSE
                """,
                [changed_at, user_id],
            )
            return cursor.rowcount == 1

    def append_verified_event(self, *, signup_request_id: str, created_at) -> None:
        with connections[self.alias].cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO signup_request_events (
                    id, signup_request_id, event_type, from_status,
                    to_status, actor_user_id, created_at
                ) VALUES (
                    gen_random_uuid(), %s, 'verified', 'pending_email_verification',
                    'pending_approval', NULL, %s
                )
                """,
                [signup_request_id, created_at],
            )


def verify_signup_email(
    token: str,
    *,
    token_verifier: EmailVerificationTokenVerifier,
    repository: SignupVerificationRepository | None = None,
    atomic_context: AbstractContextManager | None = None,
) -> None:
    """Consume one verification token and perform only the verification transition."""

    repository = repository or CentralSignupVerificationRepository()
    alias = getattr(repository, "alias", getattr(settings, "CENTRAL_DB_ALIAS", "default"))
    verifier_alias = _database_alias(token_verifier)
    if verifier_alias is not None and verifier_alias != alias:
        raise EmailVerificationConfigurationError(
            "verification token and signup state repositories must share one DB alias"
        )
    context = atomic_context or transaction.atomic(using=alias)

    with context:
        grant = token_verifier.consume(token)
        if grant is None:
            raise EmailVerificationRejected(PUBLIC_VERIFICATION_ERROR)

        changed_at = timezone.now()
        if not repository.transition_request_to_pending_approval(
            signup_request_id=grant.signup_request_id,
            user_id=grant.user_id,
            changed_at=changed_at,
        ):
            raise EmailVerificationRejected(PUBLIC_VERIFICATION_ERROR)

        if not repository.mark_email_verified(
            user_id=grant.user_id,
            changed_at=changed_at,
        ):
            raise EmailVerificationRejected(PUBLIC_VERIFICATION_ERROR)

        repository.append_verified_event(
            signup_request_id=grant.signup_request_id,
            created_at=changed_at,
        )


def _database_alias(token_verifier: EmailVerificationTokenVerifier) -> str | None:
    alias_descriptor = getattr(type(token_verifier), "alias", None)
    if alias_descriptor is None:
        return None
    alias = token_verifier.alias
    return alias if isinstance(alias, str) else None
