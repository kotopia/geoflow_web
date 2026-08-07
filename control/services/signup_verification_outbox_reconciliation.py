from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Protocol

from django.conf import settings
from django.db import connections, transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from .signup_verification_outbox_service import (
    CentralSignupVerificationOutboxRepository,
    SignupVerificationOutboxRepository,
)
from .signup_verification_service import EmailVerificationConfigurationError


@dataclass(frozen=True)
class SignupVerificationOutboxReconciliationSummary:
    eligible_missing_outbox: int
    active_outbox_ineligible: int
    expired_processing_leases: int
    duplicate_live_tokens: int


@dataclass(frozen=True)
class SignupVerificationOutboxBackfillResult:
    selected: int
    enqueued: int


class SignupVerificationOutboxReconciliationRepository(Protocol):
    alias: str

    def summarize(self, *, now: datetime) -> SignupVerificationOutboxReconciliationSummary: ...

    def lock_missing_targets(
        self,
        *,
        submitted_after: datetime,
        limit: int,
    ) -> list[str]: ...


class CentralSignupVerificationOutboxReconciliationRepository:
    def __init__(self, alias: str | None = None):
        self.alias = alias or getattr(settings, "CENTRAL_DB_ALIAS", "default")

    def summarize(self, *, now: datetime) -> SignupVerificationOutboxReconciliationSummary:
        with connections[self.alias].cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                  FROM signup_requests AS signup_request
                  JOIN users AS signup_user
                    ON signup_user.id=signup_request.user_id
                 WHERE signup_request.status='pending_email_verification'
                   AND signup_user.email_verified=FALSE
                   AND signup_user.is_active=FALSE
                   AND NOT EXISTS (
                       SELECT 1
                         FROM signup_verification_delivery_outbox AS outbox
                        WHERE outbox.signup_request_id=signup_request.id
                          AND outbox.delivery_type='signup_email_verification'
                   )
                """
            )
            eligible_missing_outbox = int(cursor.fetchone()[0])

            cursor.execute(
                """
                SELECT COUNT(*)
                  FROM signup_verification_delivery_outbox AS outbox
                  JOIN signup_requests AS signup_request
                    ON signup_request.id=outbox.signup_request_id
                  JOIN users AS signup_user
                    ON signup_user.id=signup_request.user_id
                 WHERE outbox.delivery_type='signup_email_verification'
                   AND outbox.status IN ('pending', 'processing')
                   AND NOT (
                       signup_request.status='pending_email_verification'
                       AND signup_user.email_verified=FALSE
                       AND signup_user.is_active=FALSE
                   )
                """
            )
            active_outbox_ineligible = int(cursor.fetchone()[0])

            cursor.execute(
                """
                SELECT COUNT(*)
                  FROM signup_verification_delivery_outbox
                 WHERE delivery_type='signup_email_verification'
                   AND status='processing'
                   AND claim_expires_at <= %s
                """,
                [now],
            )
            expired_processing_leases = int(cursor.fetchone()[0])

            cursor.execute(
                """
                SELECT COUNT(*)
                  FROM (
                    SELECT signup_request_id, purpose
                      FROM signup_email_verification_tokens
                     WHERE consumed_at IS NULL
                       AND revoked_at IS NULL
                     GROUP BY signup_request_id, purpose
                    HAVING COUNT(*) > 1
                  ) AS duplicate_live
                """
            )
            duplicate_live_tokens = int(cursor.fetchone()[0])

        return SignupVerificationOutboxReconciliationSummary(
            eligible_missing_outbox=eligible_missing_outbox,
            active_outbox_ineligible=active_outbox_ineligible,
            expired_processing_leases=expired_processing_leases,
            duplicate_live_tokens=duplicate_live_tokens,
        )

    def lock_missing_targets(
        self,
        *,
        submitted_after: datetime,
        limit: int,
    ) -> list[str]:
        with connections[self.alias].cursor() as cursor:
            cursor.execute(
                """
                SELECT signup_request.id
                  FROM signup_requests AS signup_request
                  JOIN users AS signup_user
                    ON signup_user.id=signup_request.user_id
                 WHERE signup_request.status='pending_email_verification'
                   AND signup_request.submitted_at >= %s
                   AND signup_user.email_verified=FALSE
                   AND signup_user.is_active=FALSE
                   AND NOT EXISTS (
                       SELECT 1
                         FROM signup_verification_delivery_outbox AS outbox
                        WHERE outbox.signup_request_id=signup_request.id
                          AND outbox.delivery_type='signup_email_verification'
                   )
                 ORDER BY signup_request.submitted_at, signup_request.id
                 FOR UPDATE OF signup_request SKIP LOCKED
                 LIMIT %s
                """,
                [submitted_after, limit],
            )
            return [str(row[0]) for row in cursor.fetchall()]


def summarize_signup_verification_outbox(
    *,
    repository: SignupVerificationOutboxReconciliationRepository | None = None,
    alias: str | None = None,
    clock: Callable[[], datetime] = timezone.now,
) -> SignupVerificationOutboxReconciliationSummary:
    resolved_alias = alias or getattr(settings, "CENTRAL_DB_ALIAS", "default")
    repository = repository or CentralSignupVerificationOutboxReconciliationRepository(
        alias=resolved_alias
    )
    _require_alias(repository, resolved_alias)
    return repository.summarize(now=clock())


@sensitive_variables("target_ids")
def queue_missing_signup_verification_outbox_batch(
    *,
    submitted_after: datetime,
    limit: int,
    repository: SignupVerificationOutboxReconciliationRepository | None = None,
    outbox_repository: SignupVerificationOutboxRepository | None = None,
    alias: str | None = None,
    atomic_context: AbstractContextManager | None = None,
    clock: Callable[[], datetime] = timezone.now,
) -> SignupVerificationOutboxBackfillResult:
    if not isinstance(submitted_after, datetime) or not timezone.is_aware(submitted_after):
        raise ValueError("submitted_after must be an aware datetime")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ValueError("backfill limit must be a positive integer")

    resolved_alias = alias or getattr(settings, "CENTRAL_DB_ALIAS", "default")
    repository = repository or CentralSignupVerificationOutboxReconciliationRepository(
        alias=resolved_alias
    )
    outbox_repository = outbox_repository or CentralSignupVerificationOutboxRepository(
        alias=resolved_alias
    )
    _require_alias(repository, resolved_alias)
    _require_alias(outbox_repository, resolved_alias)

    now = clock()
    context = atomic_context or transaction.atomic(using=resolved_alias)
    with context:
        target_ids = repository.lock_missing_targets(
            submitted_after=submitted_after,
            limit=limit,
        )
        enqueued = sum(
            bool(
                outbox_repository.enqueue(
                    signup_request_id=signup_request_id,
                    available_at=now,
                    created_at=now,
                )
            )
            for signup_request_id in target_ids
        )

    return SignupVerificationOutboxBackfillResult(
        selected=len(target_ids),
        enqueued=enqueued,
    )


def _require_alias(repository, expected_alias: str) -> None:
    repository_alias = getattr(repository, "alias", None)
    if repository_alias is not None and repository_alias != expected_alias:
        raise EmailVerificationConfigurationError(
            "outbox reconciliation repositories must share the central DB alias"
        )
