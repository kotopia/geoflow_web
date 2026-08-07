from __future__ import annotations

import re
import uuid
from contextlib import AbstractContextManager
from datetime import datetime, timedelta
from typing import Callable, Protocol

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from .signup_verification_outbox_repository import (
    CentralSignupVerificationOutboxRepository,
)
from .signup_verification_outbox_types import (
    INELIGIBLE_OUTBOX_ERROR_CODE,
    OUTBOX_STATUS_CANCELLED,
    OUTBOX_STATUS_DELIVERED,
    OUTBOX_STATUS_PENDING,
    OUTBOX_STATUS_PROCESSING,
    SIGNUP_VERIFICATION_DELIVERY_TYPE,
    SignupVerificationDeliveryClaim,
    SignupVerificationLockedDeliveryTarget,
)
from .signup_verification_service import EmailVerificationConfigurationError


_ERROR_CODE_RE = re.compile(r"^[a-z0-9_.-]{1,64}$")


class SignupVerificationOutboxEnqueueRejected(RuntimeError):
    """The signup request is no longer eligible for a delivery intent."""


class SignupVerificationOutboxRepository(Protocol):
    alias: str

    def enqueue(self, **kwargs) -> bool: ...

    def cancel_ineligible(self, **kwargs) -> int: ...

    def claim_next_due(self, **kwargs) -> SignupVerificationDeliveryClaim | None: ...

    def lock_current_claim(
        self, **kwargs
    ) -> SignupVerificationLockedDeliveryTarget | None: ...

    def mark_delivered(self, **kwargs) -> bool: ...

    def release_for_retry(self, **kwargs) -> bool: ...

    def mark_cancelled(self, **kwargs) -> bool: ...


@sensitive_variables("signup_request_id")
def enqueue_signup_email_verification_delivery(
    signup_request_id: str,
    *,
    repository: SignupVerificationOutboxRepository | None = None,
    alias: str | None = None,
    clock: Callable[[], datetime] = timezone.now,
) -> None:
    normalized_request_id = str(signup_request_id).strip()
    if not normalized_request_id:
        raise ValueError("signup_request_id is required")

    resolved_alias = alias or getattr(settings, "CENTRAL_DB_ALIAS", "default")
    repository = repository or CentralSignupVerificationOutboxRepository(
        alias=resolved_alias
    )
    _require_alias(repository, resolved_alias)

    now = clock()
    if not repository.enqueue(
        signup_request_id=normalized_request_id,
        available_at=now,
        created_at=now,
    ):
        raise SignupVerificationOutboxEnqueueRejected(
            "signup verification delivery could not be queued"
        )


@sensitive_variables("lease_id")
def claim_next_signup_email_verification_delivery(
    *,
    lease_for: timedelta,
    repository: SignupVerificationOutboxRepository | None = None,
    alias: str | None = None,
    atomic_context: AbstractContextManager | None = None,
    clock: Callable[[], datetime] = timezone.now,
    lease_factory: Callable[[], uuid.UUID] = uuid.uuid4,
) -> SignupVerificationDeliveryClaim | None:
    if lease_for <= timedelta(0):
        raise ValueError("outbox lease duration must be positive")

    resolved_alias = alias or getattr(settings, "CENTRAL_DB_ALIAS", "default")
    repository = repository or CentralSignupVerificationOutboxRepository(
        alias=resolved_alias
    )
    _require_alias(repository, resolved_alias)

    now = clock()
    lease_id = str(lease_factory())
    context = atomic_context or transaction.atomic(using=resolved_alias)
    with context:
        repository.cancel_ineligible(now=now)
        return repository.claim_next_due(
            now=now,
            lease_id=lease_id,
            claim_expires_at=now + lease_for,
        )


def validate_outbox_error_code(error_code: str) -> str:
    normalized = str(error_code).strip().lower()
    if not _ERROR_CODE_RE.fullmatch(normalized):
        raise ValueError("outbox error code is invalid")
    return normalized


def _require_alias(repository, expected_alias: str) -> None:
    repository_alias = getattr(repository, "alias", None)
    if repository_alias is not None and repository_alias != expected_alias:
        raise EmailVerificationConfigurationError(
            "signup verification outbox repositories must share the central DB alias"
        )
