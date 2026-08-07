from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Callable

from django.conf import settings
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from .signup_verification_outbox_service import (
    SignupVerificationOutboxRepository,
    claim_next_signup_email_verification_delivery,
)
from .signup_verification_outbox_worker import (
    SignupVerificationDeliveryOutcome,
    process_signup_verification_delivery_claim,
)
from .signup_verification_token_service import (
    HmacSha256VerificationKeyRing,
    SignupEmailVerificationTokenRepository,
)


@dataclass(frozen=True)
class SignupVerificationOutboxRunResult:
    claimed: bool
    outcome: str | None


@sensitive_variables("key_ring")
def process_next_signup_verification_outbox_item(
    *,
    verification_url: str,
    ttl: timedelta,
    lease_for: timedelta,
    retry_delay: timedelta,
    email_timeout: timedelta,
    max_attempts: int,
    key_ring: HmacSha256VerificationKeyRing,
    alias: str | None = None,
    outbox_repository: SignupVerificationOutboxRepository | None = None,
    token_repository: SignupEmailVerificationTokenRepository | None = None,
    clock: Callable = timezone.now,
    lease_factory=None,
    token_factory=None,
    deliver=None,
    settings_obj=settings,
) -> SignupVerificationOutboxRunResult:
    """Process at most one due outbox row; scheduling policy stays with the caller."""

    if lease_for <= timedelta(0):
        raise ValueError("outbox lease duration must be positive")
    if retry_delay <= timedelta(0):
        raise ValueError("outbox retry delay must be positive")
    if email_timeout <= timedelta(0):
        raise ValueError("email timeout must be positive")
    if lease_for <= email_timeout:
        raise ValueError("outbox lease must exceed email timeout")
    if (
        isinstance(max_attempts, bool)
        or not isinstance(max_attempts, int)
        or max_attempts <= 0
    ):
        raise ValueError("outbox max attempts must be a positive integer")

    claim_values = {
        "lease_for": lease_for,
        "repository": outbox_repository,
        "alias": alias,
        "clock": clock,
    }
    if lease_factory is not None:
        claim_values["lease_factory"] = lease_factory
    claim = claim_next_signup_email_verification_delivery(**claim_values)
    if claim is None:
        return SignupVerificationOutboxRunResult(claimed=False, outcome=None)

    process_values = {
        "claim": claim,
        "verification_url": verification_url,
        "ttl": ttl,
        "retry_at": clock() + retry_delay,
        "key_ring": key_ring,
        "alias": alias,
        "outbox_repository": outbox_repository,
        "token_repository": token_repository,
        "clock": clock,
        "email_timeout_seconds": int(email_timeout.total_seconds()),
        "max_attempts": max_attempts,
        "settings_obj": settings_obj,
    }
    if token_factory is not None:
        process_values["token_factory"] = token_factory
    if deliver is not None:
        process_values["deliver"] = deliver

    outcome: SignupVerificationDeliveryOutcome = (
        process_signup_verification_delivery_claim(**process_values)
    )
    return SignupVerificationOutboxRunResult(
        claimed=True,
        outcome=outcome.status,
    )
