from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from .signup_verification_delivery import (
    build_signup_email_verification_link,
    validate_signup_email_verification_url,
)
from .signup_verification_email_delivery import (
    SignupVerificationEmailDeliveryError,
    send_signup_email_verification_email,
)
from .signup_verification_outbox_service import (
    CentralSignupVerificationOutboxRepository,
    INELIGIBLE_OUTBOX_ERROR_CODE,
    SignupVerificationDeliveryClaim,
    SignupVerificationOutboxRepository,
    validate_outbox_error_code,
)
from .signup_verification_service import EmailVerificationConfigurationError
from .signup_verification_token_service import (
    CentralSignupEmailVerificationTokenRepository,
    HmacSha256VerificationKeyRing,
    SignupEmailVerificationTokenIssuanceRejected,
    SignupEmailVerificationTokenRepository,
    issue_signup_email_verification_token,
)


DELIVERY_ERROR_CODE = "mail.delivery_failed"
MAX_ATTEMPTS_ERROR_CODE = "mail.max_attempts_exceeded"
STALE_CLAIM_ERROR_CODE = "outbox.stale_claim"


@dataclass(frozen=True)
class SignupVerificationDeliveryOutcome:
    status: str


@sensitive_variables(
    "claim",
    "locked_target",
    "key_ring",
    "issued",
    "verification_link",
)
def process_signup_verification_delivery_claim(
    claim: SignupVerificationDeliveryClaim,
    *,
    verification_url: str,
    ttl: timedelta,
    retry_at: datetime,
    key_ring: HmacSha256VerificationKeyRing,
    alias: str | None = None,
    outbox_repository: SignupVerificationOutboxRepository | None = None,
    token_repository: SignupEmailVerificationTokenRepository | None = None,
    atomic_context: AbstractContextManager | None = None,
    clock: Callable[[], datetime] = timezone.now,
    token_factory=None,
    link_builder: Callable = build_signup_email_verification_link,
    deliver: Callable = send_signup_email_verification_email,
    email_timeout_seconds: int | None = None,
    max_attempts: int | None = None,
    settings_obj=settings,
) -> SignupVerificationDeliveryOutcome:
    """Issue a replacement token only for a live lease, then deliver after commit."""

    validate_signup_email_verification_url(verification_url)
    if ttl <= timedelta(0):
        raise ValueError("verification token ttl must be positive")

    resolved_alias = alias or getattr(settings, "CENTRAL_DB_ALIAS", "default")
    outbox_repository = outbox_repository or CentralSignupVerificationOutboxRepository(
        alias=resolved_alias
    )
    token_repository = token_repository or CentralSignupEmailVerificationTokenRepository(
        alias=resolved_alias
    )
    _require_alias(outbox_repository, resolved_alias)
    _require_alias(token_repository, resolved_alias)

    now = clock()
    if retry_at <= now:
        raise ValueError("outbox retry_at must be in the future")
    if (
        max_attempts is not None
        and (
            isinstance(max_attempts, bool)
            or not isinstance(max_attempts, int)
            or max_attempts <= 0
        )
    ):
        raise ValueError("outbox max attempts must be a positive integer")
    if max_attempts is not None and claim.attempt_count > max_attempts:
        cancelled = outbox_repository.mark_cancelled(
            outbox_id=claim.outbox_id,
            lease_id=claim.lease_id,
            cancelled_at=now,
            error_code=validate_outbox_error_code(MAX_ATTEMPTS_ERROR_CODE),
        )
        return SignupVerificationDeliveryOutcome(
            status=(
                "max_attempts_exhausted"
                if cancelled
                else "stale_after_failure"
            )
        )

    context = atomic_context or transaction.atomic(using=resolved_alias)
    try:
        with context:
            locked_target = outbox_repository.lock_current_claim(
                outbox_id=claim.outbox_id,
                lease_id=claim.lease_id,
                now=now,
            )
            if locked_target is None:
                return SignupVerificationDeliveryOutcome(status="stale")

            issuance_values = {
                "signup_request_id": locked_target.signup_request_id,
                "ttl": ttl,
                "key_ring": key_ring,
                "repository": token_repository,
                "clock": lambda: now,
                "atomic_context": nullcontext(),
            }
            if token_factory is not None:
                issuance_values["token_factory"] = token_factory
            issued = issue_signup_email_verification_token(**issuance_values)
    except SignupEmailVerificationTokenIssuanceRejected:
        cancelled = outbox_repository.mark_cancelled(
            outbox_id=claim.outbox_id,
            lease_id=claim.lease_id,
            cancelled_at=now,
            error_code=validate_outbox_error_code(INELIGIBLE_OUTBOX_ERROR_CODE),
        )
        return SignupVerificationDeliveryOutcome(
            status="cancelled" if cancelled else "stale_after_cancellation"
        )

    delivery_started_at = clock()
    if delivery_started_at >= claim.claim_expires_at:
        return SignupVerificationDeliveryOutcome(status="stale_before_delivery")
    if email_timeout_seconds is not None:
        remaining_lease = claim.claim_expires_at - delivery_started_at
        if remaining_lease <= timedelta(seconds=email_timeout_seconds):
            return SignupVerificationDeliveryOutcome(status="stale_before_delivery")

    verification_link = link_builder(verification_url, issued.token)
    try:
        deliver(
            to_email=locked_target.email,
            verification_link=verification_link,
            expires_at=issued.expires_at,
            email_timeout_seconds=email_timeout_seconds,
            settings_obj=settings_obj,
        )
    except SignupVerificationEmailDeliveryError:
        failed_at = clock()
        if max_attempts is not None and claim.attempt_count >= max_attempts:
            cancelled = outbox_repository.mark_cancelled(
                outbox_id=claim.outbox_id,
                lease_id=claim.lease_id,
                cancelled_at=failed_at,
                error_code=validate_outbox_error_code(MAX_ATTEMPTS_ERROR_CODE),
            )
            return SignupVerificationDeliveryOutcome(
                status=(
                    "max_attempts_exhausted"
                    if cancelled
                    else "stale_after_failure"
                )
            )
        released = outbox_repository.release_for_retry(
            outbox_id=claim.outbox_id,
            lease_id=claim.lease_id,
            retry_at=retry_at,
            failed_at=failed_at,
            error_code=validate_outbox_error_code(DELIVERY_ERROR_CODE),
        )
        return SignupVerificationDeliveryOutcome(
            status="retry_scheduled" if released else "stale_after_failure"
        )

    delivered = outbox_repository.mark_delivered(
        outbox_id=claim.outbox_id,
        lease_id=claim.lease_id,
        delivered_at=clock(),
    )
    return SignupVerificationDeliveryOutcome(
        status="delivered" if delivered else "stale_after_delivery"
    )


def _require_alias(repository, expected_alias: str) -> None:
    repository_alias = getattr(repository, "alias", None)
    if repository_alias is not None and repository_alias != expected_alias:
        raise EmailVerificationConfigurationError(
            "outbox worker repositories must share the central DB alias"
        )
