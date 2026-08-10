from __future__ import annotations

import re
import uuid
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from django.conf import settings
from django.db import connections, transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from .account_password_reset_delivery import (
    AccountPasswordResetEmailDeliveryError,
    build_account_password_reset_link,
    send_account_password_reset_email,
)
from .account_password_reset_token_service import (
    AccountPasswordResetTokenIssuanceRejected,
    AccountPasswordResetTokenRepository,
    CentralAccountPasswordResetTokenRepository,
    issue_account_password_reset_token,
)
from .signup_verification_token_service import HmacSha256VerificationKeyRing


PASSWORD_RESET_DELIVERY_TYPE = "account_password_reset"
INELIGIBLE_ERROR_CODE = "outbox.ineligible"
DELIVERY_ERROR_CODE = "mail.delivery_failed"
MAX_ATTEMPTS_ERROR_CODE = "mail.max_attempts_exceeded"
_ERROR_CODE_RE = re.compile(r"^[a-z0-9_.-]{1,64}$")


@dataclass(frozen=True)
class AccountPasswordResetDeliveryClaim:
    outbox_id: str
    user_id: str
    email: str
    lease_id: str
    attempt_count: int
    claim_expires_at: datetime


@dataclass(frozen=True)
class AccountPasswordResetLockedTarget:
    user_id: str
    email: str


@dataclass(frozen=True)
class AccountPasswordResetOutboxRunResult:
    claimed: bool
    outcome: str | None


class CentralAccountPasswordResetOutboxRepository:
    def __init__(self, alias: str | None = None):
        self.alias = alias or getattr(settings, "CENTRAL_DB_ALIAS", "default")

    def queue_for_email(
        self,
        *,
        email: str,
        now: datetime,
        recent_cutoff: datetime,
    ) -> bool:
        with connections[self.alias].cursor() as cursor:
            cursor.execute(
                """
                SELECT account_user.id
                  FROM users AS account_user
                 WHERE lower(account_user.email)=lower(%s)
                   AND account_user.is_active=TRUE
                   AND account_user.email_verified=TRUE
                   AND account_user.password_hash IS NOT NULL
                   AND length(trim(account_user.password_hash)) > 0
                 FOR UPDATE OF account_user
                """,
                [email],
            )
            row = cursor.fetchone()
            if row is None:
                return False
            user_id = str(row[0])
            cursor.execute(
                """
                SELECT 1
                  FROM account_password_reset_delivery_outbox
                 WHERE user_id=%s
                   AND delivery_type=%s
                   AND (
                       status IN ('pending', 'processing')
                       OR updated_at > %s
                   )
                 LIMIT 1
                """,
                [user_id, PASSWORD_RESET_DELIVERY_TYPE, recent_cutoff],
            )
            if cursor.fetchone() is not None:
                return False
            cursor.execute(
                """
                INSERT INTO account_password_reset_delivery_outbox (
                    id, user_id, delivery_type, status, available_at,
                    attempt_count, lease_id, claimed_at, claim_expires_at,
                    delivered_at, last_error_code, created_at, updated_at
                ) VALUES (
                    %s, %s, %s, 'pending', %s,
                    0, NULL, NULL, NULL, NULL, NULL, %s, %s
                )
                ON CONFLICT DO NOTHING
                RETURNING id
                """,
                [
                    str(uuid.uuid4()),
                    user_id,
                    PASSWORD_RESET_DELIVERY_TYPE,
                    now,
                    now,
                    now,
                ],
            )
            return cursor.fetchone() is not None

    def cancel_ineligible(self, *, now: datetime) -> int:
        with connections[self.alias].cursor() as cursor:
            cursor.execute(
                """
                UPDATE account_password_reset_delivery_outbox AS outbox
                   SET status='cancelled',
                       lease_id=NULL,
                       claimed_at=NULL,
                       claim_expires_at=NULL,
                       delivered_at=NULL,
                       last_error_code=%s,
                       updated_at=%s
                  FROM users AS account_user
                 WHERE account_user.id=outbox.user_id
                   AND outbox.delivery_type=%s
                   AND (
                       outbox.status='pending'
                       OR (
                           outbox.status='processing'
                           AND outbox.claim_expires_at <= %s
                       )
                   )
                   AND NOT (
                       account_user.is_active=TRUE
                       AND account_user.email_verified=TRUE
                       AND account_user.password_hash IS NOT NULL
                       AND length(trim(account_user.password_hash)) > 0
                   )
                """,
                [INELIGIBLE_ERROR_CODE, now, PASSWORD_RESET_DELIVERY_TYPE, now],
            )
            return cursor.rowcount

    def claim_next_due(
        self,
        *,
        now: datetime,
        lease_id: str,
        claim_expires_at: datetime,
    ) -> AccountPasswordResetDeliveryClaim | None:
        with connections[self.alias].cursor() as cursor:
            cursor.execute(
                """
                WITH candidate AS (
                    SELECT outbox.id
                      FROM account_password_reset_delivery_outbox AS outbox
                      JOIN users AS account_user ON account_user.id=outbox.user_id
                     WHERE outbox.delivery_type=%s
                       AND (
                           (outbox.status='pending' AND outbox.available_at <= %s)
                           OR (
                               outbox.status='processing'
                               AND outbox.claim_expires_at <= %s
                           )
                       )
                       AND account_user.is_active=TRUE
                       AND account_user.email_verified=TRUE
                       AND account_user.password_hash IS NOT NULL
                       AND length(trim(account_user.password_hash)) > 0
                     ORDER BY outbox.available_at, outbox.created_at, outbox.id
                     FOR UPDATE OF outbox SKIP LOCKED
                     LIMIT 1
                )
                UPDATE account_password_reset_delivery_outbox AS outbox
                   SET status='processing',
                       lease_id=%s,
                       claimed_at=%s,
                       claim_expires_at=%s,
                       attempt_count=outbox.attempt_count + 1,
                       last_error_code=NULL,
                       updated_at=%s
                  FROM candidate, users AS account_user
                 WHERE outbox.id=candidate.id
                   AND account_user.id=outbox.user_id
                RETURNING outbox.id, outbox.user_id, account_user.email,
                          outbox.attempt_count
                """,
                [
                    PASSWORD_RESET_DELIVERY_TYPE,
                    now,
                    now,
                    lease_id,
                    now,
                    claim_expires_at,
                    now,
                ],
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return AccountPasswordResetDeliveryClaim(
            outbox_id=str(row[0]),
            user_id=str(row[1]),
            email=str(row[2]),
            lease_id=lease_id,
            attempt_count=int(row[3]),
            claim_expires_at=claim_expires_at,
        )

    def lock_current_claim(
        self,
        *,
        outbox_id: str,
        lease_id: str,
        now: datetime,
    ) -> AccountPasswordResetLockedTarget | None:
        with connections[self.alias].cursor() as cursor:
            cursor.execute(
                """
                SELECT account_user.id, account_user.email
                  FROM account_password_reset_delivery_outbox AS outbox
                  JOIN users AS account_user ON account_user.id=outbox.user_id
                 WHERE outbox.id=%s
                   AND outbox.delivery_type=%s
                   AND outbox.status='processing'
                   AND outbox.lease_id=%s
                   AND outbox.claim_expires_at > %s
                   AND account_user.is_active=TRUE
                   AND account_user.email_verified=TRUE
                   AND account_user.password_hash IS NOT NULL
                   AND length(trim(account_user.password_hash)) > 0
                 FOR UPDATE OF outbox, account_user
                """,
                [outbox_id, PASSWORD_RESET_DELIVERY_TYPE, lease_id, now],
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return AccountPasswordResetLockedTarget(
            user_id=str(row[0]),
            email=str(row[1]),
        )

    def mark_delivered(
        self,
        *,
        outbox_id: str,
        lease_id: str,
        delivered_at: datetime,
    ) -> bool:
        return self._finish_claim(
            outbox_id=outbox_id,
            lease_id=lease_id,
            status="delivered",
            timestamp=delivered_at,
            error_code=None,
        )

    def release_for_retry(
        self,
        *,
        outbox_id: str,
        lease_id: str,
        retry_at: datetime,
        failed_at: datetime,
        error_code: str,
    ) -> bool:
        with connections[self.alias].cursor() as cursor:
            cursor.execute(
                """
                UPDATE account_password_reset_delivery_outbox
                   SET status='pending', available_at=%s,
                       lease_id=NULL, claimed_at=NULL, claim_expires_at=NULL,
                       delivered_at=NULL, last_error_code=%s, updated_at=%s
                 WHERE id=%s
                   AND delivery_type=%s
                   AND status='processing'
                   AND lease_id=%s
                """,
                [
                    retry_at,
                    _validate_error_code(error_code),
                    failed_at,
                    outbox_id,
                    PASSWORD_RESET_DELIVERY_TYPE,
                    lease_id,
                ],
            )
            return cursor.rowcount == 1

    def mark_cancelled(
        self,
        *,
        outbox_id: str,
        lease_id: str,
        cancelled_at: datetime,
        error_code: str,
    ) -> bool:
        return self._finish_claim(
            outbox_id=outbox_id,
            lease_id=lease_id,
            status="cancelled",
            timestamp=cancelled_at,
            error_code=_validate_error_code(error_code),
        )

    def _finish_claim(
        self,
        *,
        outbox_id: str,
        lease_id: str,
        status: str,
        timestamp: datetime,
        error_code: str | None,
    ) -> bool:
        delivered_at = timestamp if status == "delivered" else None
        with connections[self.alias].cursor() as cursor:
            cursor.execute(
                """
                UPDATE account_password_reset_delivery_outbox
                   SET status=%s,
                       lease_id=NULL, claimed_at=NULL, claim_expires_at=NULL,
                       delivered_at=%s, last_error_code=%s, updated_at=%s
                 WHERE id=%s
                   AND delivery_type=%s
                   AND status='processing'
                   AND lease_id=%s
                """,
                [
                    status,
                    delivered_at,
                    error_code,
                    timestamp,
                    outbox_id,
                    PASSWORD_RESET_DELIVERY_TYPE,
                    lease_id,
                ],
            )
            return cursor.rowcount == 1


@sensitive_variables("email")
def queue_account_password_reset_request(
    email: str,
    *,
    cooldown: timedelta,
    alias: str | None = None,
    repository: CentralAccountPasswordResetOutboxRepository | None = None,
    clock: Callable[[], datetime] = timezone.now,
) -> bool:
    """Queue eligible accounts while allowing callers to keep responses generic."""

    normalized_email = str(email or "").strip().lower()
    if not normalized_email:
        return False
    if cooldown <= timedelta(0):
        raise ValueError("password reset cooldown must be positive")
    resolved_alias = alias or getattr(settings, "CENTRAL_DB_ALIAS", "default")
    repository = repository or CentralAccountPasswordResetOutboxRepository(resolved_alias)
    now = clock()
    with transaction.atomic(using=resolved_alias):
        return repository.queue_for_email(
            email=normalized_email,
            now=now,
            recent_cutoff=now - cooldown,
        )


def claim_next_account_password_reset_delivery(
    *,
    lease_for: timedelta,
    alias: str | None = None,
    repository: CentralAccountPasswordResetOutboxRepository | None = None,
    clock: Callable[[], datetime] = timezone.now,
    lease_factory: Callable[[], uuid.UUID] = uuid.uuid4,
) -> AccountPasswordResetDeliveryClaim | None:
    if lease_for <= timedelta(0):
        raise ValueError("password reset outbox lease must be positive")
    resolved_alias = alias or getattr(settings, "CENTRAL_DB_ALIAS", "default")
    repository = repository or CentralAccountPasswordResetOutboxRepository(resolved_alias)
    now = clock()
    with transaction.atomic(using=resolved_alias):
        repository.cancel_ineligible(now=now)
        return repository.claim_next_due(
            now=now,
            lease_id=str(lease_factory()),
            claim_expires_at=now + lease_for,
        )


@sensitive_variables("claim", "key_ring", "issued", "reset_link")
def process_account_password_reset_delivery_claim(
    claim: AccountPasswordResetDeliveryClaim,
    *,
    reset_url: str,
    ttl: timedelta,
    retry_at: datetime,
    key_ring: HmacSha256VerificationKeyRing,
    alias: str | None = None,
    outbox_repository: CentralAccountPasswordResetOutboxRepository | None = None,
    token_repository: AccountPasswordResetTokenRepository | None = None,
    clock: Callable[[], datetime] = timezone.now,
    token_factory=None,
    deliver: Callable = send_account_password_reset_email,
    email_timeout_seconds: int | None = None,
    max_attempts: int = 5,
    settings_obj=settings,
) -> str:
    resolved_alias = alias or getattr(settings, "CENTRAL_DB_ALIAS", "default")
    outbox_repository = outbox_repository or CentralAccountPasswordResetOutboxRepository(
        resolved_alias
    )
    token_repository = token_repository or CentralAccountPasswordResetTokenRepository(
        resolved_alias
    )
    now = clock()
    if retry_at <= now:
        raise ValueError("password reset retry_at must be in the future")
    if max_attempts <= 0:
        raise ValueError("password reset max attempts must be positive")
    if claim.attempt_count > max_attempts:
        cancelled = outbox_repository.mark_cancelled(
            outbox_id=claim.outbox_id,
            lease_id=claim.lease_id,
            cancelled_at=now,
            error_code=MAX_ATTEMPTS_ERROR_CODE,
        )
        return "max_attempts_exhausted" if cancelled else "stale_after_failure"

    try:
        with transaction.atomic(using=resolved_alias):
            locked_target = outbox_repository.lock_current_claim(
                outbox_id=claim.outbox_id,
                lease_id=claim.lease_id,
                now=now,
            )
            if locked_target is None:
                return "stale"
            issue_kwargs = {
                "user_id": locked_target.user_id,
                "ttl": ttl,
                "key_ring": key_ring,
                "repository": token_repository,
                "clock": lambda: now,
                "atomic_context": nullcontext(),
            }
            if token_factory is not None:
                issue_kwargs["token_factory"] = token_factory
            issued = issue_account_password_reset_token(**issue_kwargs)
    except AccountPasswordResetTokenIssuanceRejected:
        cancelled = outbox_repository.mark_cancelled(
            outbox_id=claim.outbox_id,
            lease_id=claim.lease_id,
            cancelled_at=now,
            error_code=INELIGIBLE_ERROR_CODE,
        )
        return "cancelled" if cancelled else "stale_after_cancellation"

    delivery_started_at = clock()
    if delivery_started_at >= claim.claim_expires_at:
        return "stale_before_delivery"
    if email_timeout_seconds is not None:
        remaining = claim.claim_expires_at - delivery_started_at
        if remaining <= timedelta(seconds=email_timeout_seconds):
            return "stale_before_delivery"

    reset_link = build_account_password_reset_link(reset_url, issued.token)
    try:
        deliver(
            to_email=locked_target.email,
            reset_link=reset_link,
            expires_at=issued.expires_at,
            email_timeout_seconds=email_timeout_seconds,
            settings_obj=settings_obj,
        )
    except AccountPasswordResetEmailDeliveryError:
        failed_at = clock()
        if claim.attempt_count >= max_attempts:
            cancelled = outbox_repository.mark_cancelled(
                outbox_id=claim.outbox_id,
                lease_id=claim.lease_id,
                cancelled_at=failed_at,
                error_code=MAX_ATTEMPTS_ERROR_CODE,
            )
            return "max_attempts_exhausted" if cancelled else "stale_after_failure"
        released = outbox_repository.release_for_retry(
            outbox_id=claim.outbox_id,
            lease_id=claim.lease_id,
            retry_at=retry_at,
            failed_at=failed_at,
            error_code=DELIVERY_ERROR_CODE,
        )
        return "retry_scheduled" if released else "stale_after_failure"

    delivered = outbox_repository.mark_delivered(
        outbox_id=claim.outbox_id,
        lease_id=claim.lease_id,
        delivered_at=clock(),
    )
    return "delivered" if delivered else "stale_after_delivery"


def process_next_account_password_reset_outbox_item(
    *,
    reset_url: str,
    ttl: timedelta,
    lease_for: timedelta,
    retry_delay: timedelta,
    email_timeout: timedelta,
    max_attempts: int,
    key_ring: HmacSha256VerificationKeyRing,
    alias: str | None = None,
    outbox_repository: CentralAccountPasswordResetOutboxRepository | None = None,
    token_repository: AccountPasswordResetTokenRepository | None = None,
    clock: Callable[[], datetime] = timezone.now,
    lease_factory=None,
    token_factory=None,
    deliver=None,
    settings_obj=settings,
) -> AccountPasswordResetOutboxRunResult:
    claim_kwargs = {
        "lease_for": lease_for,
        "alias": alias,
        "repository": outbox_repository,
        "clock": clock,
    }
    if lease_factory is not None:
        claim_kwargs["lease_factory"] = lease_factory
    claim = claim_next_account_password_reset_delivery(**claim_kwargs)
    if claim is None:
        return AccountPasswordResetOutboxRunResult(claimed=False, outcome=None)
    process_kwargs = {
        "claim": claim,
        "reset_url": reset_url,
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
        process_kwargs["token_factory"] = token_factory
    if deliver is not None:
        process_kwargs["deliver"] = deliver
    return AccountPasswordResetOutboxRunResult(
        claimed=True,
        outcome=process_account_password_reset_delivery_claim(**process_kwargs),
    )


def _validate_error_code(error_code: str) -> str:
    normalized = str(error_code or "").strip().lower()
    if not _ERROR_CODE_RE.fullmatch(normalized):
        raise ValueError("password reset outbox error code is invalid")
    return normalized
