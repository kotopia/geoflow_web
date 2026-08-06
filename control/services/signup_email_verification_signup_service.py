from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction

from .signup_service import (
    CentralSignupRepository,
    SignupRepository,
    SignupRequestInput,
    create_signup_request,
)
from .signup_verification_service import EmailVerificationConfigurationError
from .signup_verification_token_service import (
    CentralSignupEmailVerificationTokenRepository,
    HmacSha256VerificationKeyRing,
    SignupEmailVerificationTokenRepository,
    issue_signup_email_verification_token,
)


@dataclass(frozen=True)
class PendingSignupEmailVerification:
    """Raw token returned once to the delivery boundary after atomic persistence."""

    signup_request_id: str
    token: str
    expires_at: datetime


def create_signup_request_with_verification_token(
    data: SignupRequestInput,
    *,
    ttl: timedelta,
    key_ring: HmacSha256VerificationKeyRing,
    alias: str | None = None,
    signup_repository: SignupRepository | None = None,
    token_repository: SignupEmailVerificationTokenRepository | None = None,
    atomic_context: AbstractContextManager | None = None,
    token_factory=None,
) -> PendingSignupEmailVerification:
    """Create the inactive account, request, event, and token digest atomically."""

    resolved_alias = alias or getattr(settings, "CENTRAL_DB_ALIAS", "default")
    signup_repository = signup_repository or CentralSignupRepository(
        alias=resolved_alias
    )
    token_repository = token_repository or (
        CentralSignupEmailVerificationTokenRepository(alias=resolved_alias)
    )

    _require_repository_alias(signup_repository, resolved_alias)
    _require_repository_alias(token_repository, resolved_alias)

    context = atomic_context or transaction.atomic(using=resolved_alias)
    with context:
        receipt = create_signup_request(
            data,
            repository=signup_repository,
            atomic_context=nullcontext(),
        )
        issuance_values = {
            "signup_request_id": receipt.signup_request_id,
            "ttl": ttl,
            "key_ring": key_ring,
            "repository": token_repository,
            "atomic_context": nullcontext(),
        }
        if token_factory is not None:
            issuance_values["token_factory"] = token_factory
        issued = issue_signup_email_verification_token(**issuance_values)

    return PendingSignupEmailVerification(
        signup_request_id=receipt.signup_request_id,
        token=issued.token,
        expires_at=issued.expires_at,
    )


def _require_repository_alias(repository, expected_alias: str) -> None:
    repository_alias = getattr(repository, "alias", None)
    if repository_alias is not None and repository_alias != expected_alias:
        raise EmailVerificationConfigurationError(
            "signup and verification token repositories must share the central DB alias"
        )
