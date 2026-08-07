from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from typing import Callable

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from .signup_service import (
    PUBLIC_SIGNUP_ERROR,
    CentralSignupRepository,
    SignupRepository,
    SignupRequestInput,
    SignupRequestRejected,
    create_signup_request,
)
from .signup_verification_outbox_service import (
    CentralSignupVerificationOutboxRepository,
    SignupVerificationOutboxEnqueueRejected,
    SignupVerificationOutboxRepository,
)
from .signup_verification_service import EmailVerificationConfigurationError


@dataclass(frozen=True)
class QueuedSignupEmailVerification:
    signup_request_id: str = field(repr=False)


@sensitive_variables("data", "receipt")
def create_signup_request_with_verification_outbox(
    data: SignupRequestInput,
    *,
    alias: str | None = None,
    signup_repository: SignupRepository | None = None,
    outbox_repository: SignupVerificationOutboxRepository | None = None,
    atomic_context: AbstractContextManager | None = None,
    clock: Callable = timezone.now,
) -> QueuedSignupEmailVerification:
    """Create inactive signup state and one delivery intent in one transaction."""

    resolved_alias = alias or getattr(settings, "CENTRAL_DB_ALIAS", "default")
    signup_repository = signup_repository or CentralSignupRepository(
        alias=resolved_alias
    )
    outbox_repository = outbox_repository or CentralSignupVerificationOutboxRepository(
        alias=resolved_alias
    )
    _require_alias(signup_repository, resolved_alias)
    _require_alias(outbox_repository, resolved_alias)

    now = clock()
    context = atomic_context or transaction.atomic(using=resolved_alias)
    with context:
        receipt = create_signup_request(
            data,
            repository=signup_repository,
            atomic_context=nullcontext(),
        )
        queued = outbox_repository.enqueue(
            signup_request_id=receipt.signup_request_id,
            available_at=now,
            created_at=now,
        )
        if not queued:
            raise SignupRequestRejected(PUBLIC_SIGNUP_ERROR)

    return QueuedSignupEmailVerification(
        signup_request_id=receipt.signup_request_id,
    )


def _require_alias(repository, expected_alias: str) -> None:
    repository_alias = getattr(repository, "alias", None)
    if repository_alias is not None and repository_alias != expected_alias:
        raise EmailVerificationConfigurationError(
            "signup and delivery outbox repositories must share the central DB alias"
        )
