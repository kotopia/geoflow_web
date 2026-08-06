from __future__ import annotations

import uuid
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Literal, Protocol

from django.conf import settings
from django.db import connections, transaction
from django.utils import timezone


ExpirableSignupStatus = Literal[
    "pending_email_verification",
    "pending_approval",
]
_EXPIRATION_REASON_BY_STATUS = {
    "pending_email_verification": "email_verification_timeout",
    "pending_approval": "approval_timeout",
}
_AGE_COLUMN_BY_STATUS = {
    "pending_email_verification": "submitted_at",
    "pending_approval": "updated_at",
}
_EMAIL_VERIFIED_BY_STATUS = {
    "pending_email_verification": False,
    "pending_approval": True,
}


class SignupRequestExpirationRepository(Protocol):
    alias: str

    def expire_batch(
        self,
        *,
        status: ExpirableSignupStatus,
        cutoff: datetime,
        expired_at: datetime,
        reason_code: str,
        batch_size: int,
    ) -> tuple[str, ...]: ...

    def append_expired_events(
        self,
        *,
        signup_request_ids: tuple[str, ...],
        from_status: ExpirableSignupStatus,
        reason_code: str,
        created_at: datetime,
    ) -> None: ...


class CentralSignupRequestExpirationRepository:
    def __init__(self, alias: str | None = None):
        self.alias = alias or getattr(settings, "CENTRAL_DB_ALIAS", "default")

    def expire_batch(
        self,
        *,
        status: ExpirableSignupStatus,
        cutoff: datetime,
        expired_at: datetime,
        reason_code: str,
        batch_size: int,
    ) -> tuple[str, ...]:
        age_column = _AGE_COLUMN_BY_STATUS[status]
        expected_email_verified = _EMAIL_VERIFIED_BY_STATUS[status]
        sql = f"""
            WITH eligible AS (
                SELECT signup_request.id
                  FROM signup_requests AS signup_request
                  JOIN users AS signup_user
                    ON signup_user.id=signup_request.user_id
                 WHERE signup_request.status=%s
                   AND signup_request.{age_column} <= %s
                   AND signup_user.email_verified=%s
                   AND signup_user.is_active=FALSE
                 ORDER BY signup_request.{age_column}, signup_request.id
                 FOR UPDATE OF signup_request SKIP LOCKED
                 LIMIT %s
            )
            UPDATE signup_requests AS signup_request
               SET status='expired',
                   decided_at=%s,
                   decided_by_user_id=NULL,
                   decision_reason_code=%s,
                   decision_note=NULL,
                   version=version + 1,
                   updated_at=%s
              FROM eligible
             WHERE signup_request.id=eligible.id
            RETURNING signup_request.id
        """
        with connections[self.alias].cursor() as cursor:
            cursor.execute(
                sql,
                [
                    status,
                    cutoff,
                    expected_email_verified,
                    batch_size,
                    expired_at,
                    reason_code,
                    expired_at,
                ],
            )
            return tuple(str(row[0]) for row in cursor.fetchall())

    def append_expired_events(
        self,
        *,
        signup_request_ids: tuple[str, ...],
        from_status: ExpirableSignupStatus,
        reason_code: str,
        created_at: datetime,
    ) -> None:
        if not signup_request_ids:
            return
        rows = [
            (
                uuid.uuid4(),
                signup_request_id,
                from_status,
                reason_code,
                created_at,
            )
            for signup_request_id in signup_request_ids
        ]
        with connections[self.alias].cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO signup_request_events (
                    id, signup_request_id, event_type, from_status,
                    to_status, actor_user_id, reason_code, note, created_at
                ) VALUES (
                    %s, %s, 'expired', %s,
                    'expired', NULL, %s, NULL, %s
                )
                """,
                rows,
            )


def expire_signup_requests(
    *,
    status: ExpirableSignupStatus,
    cutoff: datetime,
    batch_size: int = 100,
    repository: SignupRequestExpirationRepository | None = None,
    atomic_context: AbstractContextManager | None = None,
    clock=timezone.now,
) -> int:
    """Expire one bounded batch while leaving central users inactive."""

    if status not in _EXPIRATION_REASON_BY_STATUS:
        raise ValueError("status is not expirable")
    if not isinstance(cutoff, datetime):
        raise ValueError("cutoff must be a datetime")
    if not 1 <= batch_size <= 500:
        raise ValueError("batch_size must be between 1 and 500")

    expired_at = clock()
    if cutoff > expired_at:
        raise ValueError("cutoff must not be in the future")

    repository = repository or CentralSignupRequestExpirationRepository()
    alias = getattr(
        repository,
        "alias",
        getattr(settings, "CENTRAL_DB_ALIAS", "default"),
    )
    context = atomic_context or transaction.atomic(using=alias)
    reason_code = _EXPIRATION_REASON_BY_STATUS[status]

    with context:
        expired_ids = repository.expire_batch(
            status=status,
            cutoff=cutoff,
            expired_at=expired_at,
            reason_code=reason_code,
            batch_size=batch_size,
        )
        repository.append_expired_events(
            signup_request_ids=expired_ids,
            from_status=status,
            reason_code=reason_code,
            created_at=expired_at,
        )

    return len(expired_ids)
