from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Protocol

from django.conf import settings
from django.db import connections, transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from .signup_verification_outbox_service import (
    CentralSignupVerificationOutboxRepository,
    SIGNUP_VERIFICATION_DELIVERY_TYPE,
    SignupVerificationOutboxRepository,
)
from .signup_verification_service import EmailVerificationConfigurationError


@dataclass(frozen=True)
class SignupVerificationResendOutboxTarget:
    signup_request_id: str = field(repr=False)


class SignupVerificationResendOutboxRepository(Protocol):
    alias: str

    def lock_eligible_target(
        self,
        *,
        email: str,
        recent_delivery_cutoff: datetime,
    ) -> SignupVerificationResendOutboxTarget | None: ...


class CentralSignupVerificationResendOutboxRepository:
    def __init__(self, alias: str | None = None):
        self.alias = alias or getattr(settings, "CENTRAL_DB_ALIAS", "default")

    def lock_eligible_target(
        self,
        *,
        email: str,
        recent_delivery_cutoff: datetime,
    ) -> SignupVerificationResendOutboxTarget | None:
        with connections[self.alias].cursor() as cursor:
            cursor.execute(
                """
                SELECT signup_request.id
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
                  FROM signup_verification_delivery_outbox
                 WHERE signup_request_id=%s
                   AND delivery_type=%s
                   AND (
                       status IN ('pending', 'processing')
                       OR updated_at > %s
                   )
                 LIMIT 1
                """,
                [
                    signup_request_id,
                    SIGNUP_VERIFICATION_DELIVERY_TYPE,
                    recent_delivery_cutoff,
                ],
            )
            if cursor.fetchone() is not None:
                return None

        return SignupVerificationResendOutboxTarget(
            signup_request_id=signup_request_id,
        )


@sensitive_variables("email")
def queue_signup_email_verification_resend(
    email: str,
    *,
    cooldown: timedelta,
    alias: str | None = None,
    resend_repository: SignupVerificationResendOutboxRepository | None = None,
    outbox_repository: SignupVerificationOutboxRepository | None = None,
    atomic_context: AbstractContextManager | None = None,
    clock: Callable[[], datetime] = timezone.now,
) -> bool:
    """Queue one resend intent without creating or returning a raw token."""

    normalized_email = str(email).strip().lower()
    if not normalized_email:
        raise ValueError("email is required")
    if cooldown <= timedelta(0):
        raise ValueError("verification resend cooldown must be positive")

    resolved_alias = alias or getattr(settings, "CENTRAL_DB_ALIAS", "default")
    resend_repository = resend_repository or (
        CentralSignupVerificationResendOutboxRepository(alias=resolved_alias)
    )
    outbox_repository = outbox_repository or CentralSignupVerificationOutboxRepository(
        alias=resolved_alias
    )
    _require_alias(resend_repository, resolved_alias)
    _require_alias(outbox_repository, resolved_alias)

    now = clock()
    context = atomic_context or transaction.atomic(using=resolved_alias)
    with context:
        target = resend_repository.lock_eligible_target(
            email=normalized_email,
            recent_delivery_cutoff=now - cooldown,
        )
        if target is None:
            return False
        return outbox_repository.enqueue(
            signup_request_id=target.signup_request_id,
            available_at=now,
            created_at=now,
        )


def _require_alias(repository, expected_alias: str) -> None:
    repository_alias = getattr(repository, "alias", None)
    if repository_alias is not None and repository_alias != expected_alias:
        raise EmailVerificationConfigurationError(
            "verification resend outbox repositories must share the central DB alias"
        )
