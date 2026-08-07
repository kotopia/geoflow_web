from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Protocol

from django.conf import settings
from django.db import connections, transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from .signup_verification_outbox_feature import (
    signup_verification_outbox_enabled,
)
from .signup_verification_service import EmailVerificationConfigurationError
from .signup_verification_token_service import (
    CentralSignupEmailVerificationTokenRepository,
    HmacSha256VerificationKeyRing,
    SignupEmailVerificationTokenRepository,
    issue_signup_email_verification_token,
)


@dataclass(frozen=True)
class SignupVerificationResendTarget:
    signup_request_id: str = field(repr=False)
    email: str = field(repr=False)


@dataclass(frozen=True)
class PendingSignupVerificationResend:
    signup_request_id: str = field(repr=False)
    email: str = field(repr=False)
    token: str = field(repr=False)
    expires_at: datetime


class SignupVerificationResendRepository(Protocol):
    alias: str

    def lock_eligible_target(
        self,
        *,
        email: str,
        recent_token_cutoff: datetime,
    ) -> SignupVerificationResendTarget | None: ...


class CentralSignupVerificationResendRepository:
    def __init__(self, alias: str | None = None):
        self.alias = alias or getattr(settings, "CENTRAL_DB_ALIAS", "default")

    def lock_eligible_target(
        self,
        *,
        email: str,
        recent_token_cutoff: datetime,
    ) -> SignupVerificationResendTarget | None:
        """Lock one open request and reject a resend inside the cooldown window."""

        with connections[self.alias].cursor() as cursor:
            cursor.execute(
                """
                SELECT signup_request.id, signup_user.email
                  FROM signup_requests AS signup_request
                  JOIN users AS signup_user
                    ON signup_user.id=signup_request.user_id
                 WHERE lower(signup_user.email)=lower(%s)
                   AND signup_request.status='pending_email_verification'
                   AND signup_user.email_verified=FALSE
                   AND signup_user.is_active=FALSE
                 LIMIT 1
                   FOR UPDATE OF signup_request
                """,
                [email],
            )
            row = cursor.fetchone()
            if row is None:
                return None

            signup_request_id = str(row[0])
            cursor.execute(
                """
                SELECT 1
                  FROM signup_email_verification_tokens
                 WHERE signup_request_id=%s
                   AND created_at > %s
                 LIMIT 1
                """,
                [signup_request_id, recent_token_cutoff],
            )
            if cursor.fetchone() is not None:
                return None

        return SignupVerificationResendTarget(
            signup_request_id=signup_request_id,
            email=str(row[1]),
        )


@sensitive_variables("email", "key_ring", "issued")
def prepare_signup_email_verification_resend(
    email: str,
    *,
    ttl: timedelta,
    cooldown: timedelta,
    key_ring: HmacSha256VerificationKeyRing,
    alias: str | None = None,
    resend_repository: SignupVerificationResendRepository | None = None,
    token_repository: SignupEmailVerificationTokenRepository | None = None,
    atomic_context: AbstractContextManager | None = None,
    clock: Callable[[], datetime] = timezone.now,
    token_factory: Callable[[int], str] | None = None,
) -> PendingSignupVerificationResend | None:
    """Issue a fresh digest only for an eligible, row-locked pending request."""

    if signup_verification_outbox_enabled():
        raise EmailVerificationConfigurationError(
            "direct verification resend is disabled while outbox delivery is enabled"
        )

    normalized_email = str(email).strip().lower()
    if not normalized_email:
        raise ValueError("email is required")
    if ttl <= timedelta(0):
        raise ValueError("verification token ttl must be positive")
    if cooldown <= timedelta(0):
        raise ValueError("verification resend cooldown must be positive")

    resolved_alias = alias or getattr(settings, "CENTRAL_DB_ALIAS", "default")
    resend_repository = resend_repository or (
        CentralSignupVerificationResendRepository(alias=resolved_alias)
    )
    token_repository = token_repository or (
        CentralSignupEmailVerificationTokenRepository(alias=resolved_alias)
    )
    _require_alias(resend_repository, resolved_alias)
    _require_alias(token_repository, resolved_alias)

    now = clock()
    context = atomic_context or transaction.atomic(using=resolved_alias)
    with context:
        target = resend_repository.lock_eligible_target(
            email=normalized_email,
            recent_token_cutoff=now - cooldown,
        )
        if target is None:
            return None

        issuance_values = {
            "signup_request_id": target.signup_request_id,
            "ttl": ttl,
            "key_ring": key_ring,
            "repository": token_repository,
            "clock": lambda: now,
            "atomic_context": nullcontext(),
        }
        if token_factory is not None:
            issuance_values["token_factory"] = token_factory
        issued = issue_signup_email_verification_token(**issuance_values)

    return PendingSignupVerificationResend(
        signup_request_id=target.signup_request_id,
        email=target.email,
        token=issued.token,
        expires_at=issued.expires_at,
    )


def _require_alias(repository, expected_alias: str) -> None:
    repository_alias = getattr(repository, "alias", None)
    if repository_alias is not None and repository_alias != expected_alias:
        raise EmailVerificationConfigurationError(
            "verification resend repositories must share the central DB alias"
        )
