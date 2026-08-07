from __future__ import annotations

import uuid

from django.conf import settings
from django.db import connections

from .signup_verification_outbox_types import (
    INELIGIBLE_OUTBOX_ERROR_CODE,
    SIGNUP_VERIFICATION_DELIVERY_TYPE,
    SignupVerificationDeliveryClaim,
    SignupVerificationLockedDeliveryTarget,
)


class CentralSignupVerificationOutboxRepository:
    def __init__(self, alias: str | None = None):
        self.alias = alias or getattr(settings, "CENTRAL_DB_ALIAS", "default")

    def enqueue(
        self,
        *,
        signup_request_id: str,
        available_at: datetime,
        created_at: datetime,
    ) -> bool:
        outbox_id = str(uuid.uuid4())
        with connections[self.alias].cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO signup_verification_delivery_outbox (
                    id, signup_request_id, delivery_type, status,
                    available_at, attempt_count, lease_id, claimed_at,
                    claim_expires_at, delivered_at, last_error_code,
                    created_at, updated_at
                )
                SELECT %s, signup_request.id, %s, 'pending',
                       %s, 0, NULL, NULL, NULL, NULL, NULL, %s, %s
                  FROM signup_requests AS signup_request
                  JOIN users AS signup_user
                    ON signup_user.id=signup_request.user_id
                 WHERE signup_request.id=%s
                   AND signup_request.status='pending_email_verification'
                   AND signup_user.email_verified=FALSE
                   AND signup_user.is_active=FALSE
                   AND NOT EXISTS (
                       SELECT 1
                         FROM signup_verification_delivery_outbox AS existing
                        WHERE existing.signup_request_id=signup_request.id
                          AND existing.delivery_type=%s
                          AND existing.status IN ('pending', 'processing')
                   )
                ON CONFLICT DO NOTHING
                RETURNING id
                """,
                [
                    outbox_id,
                    SIGNUP_VERIFICATION_DELIVERY_TYPE,
                    available_at,
                    created_at,
                    created_at,
                    signup_request_id,
                    SIGNUP_VERIFICATION_DELIVERY_TYPE,
                ],
            )
            return cursor.fetchone() is not None


    def cancel_ineligible(self, *, now: datetime) -> int:
        with connections[self.alias].cursor() as cursor:
            cursor.execute(
                """
                UPDATE signup_verification_delivery_outbox AS outbox
                   SET status='cancelled',
                       lease_id=NULL,
                       claimed_at=NULL,
                       claim_expires_at=NULL,
                       delivered_at=NULL,
                       last_error_code=%s,
                       updated_at=%s
                  FROM signup_requests AS signup_request,
                       users AS signup_user
                 WHERE signup_request.id=outbox.signup_request_id
                   AND signup_user.id=signup_request.user_id
                   AND outbox.delivery_type=%s
                   AND (
                       outbox.status='pending'
                       OR (
                           outbox.status='processing'
                           AND outbox.claim_expires_at <= %s
                       )
                   )
                   AND NOT (
                       signup_request.status='pending_email_verification'
                       AND signup_user.email_verified=FALSE
                       AND signup_user.is_active=FALSE
                   )
                """,
                [
                    INELIGIBLE_OUTBOX_ERROR_CODE,
                    now,
                    SIGNUP_VERIFICATION_DELIVERY_TYPE,
                    now,
                ],
            )
            return cursor.rowcount

    def claim_next_due(
        self,
        *,
        now: datetime,
        lease_id: str,
        claim_expires_at: datetime,
    ) -> SignupVerificationDeliveryClaim | None:
        with connections[self.alias].cursor() as cursor:
            cursor.execute(
                """
                WITH candidate AS (
                    SELECT outbox.id
                      FROM signup_verification_delivery_outbox AS outbox
                      JOIN signup_requests AS signup_request
                        ON signup_request.id=outbox.signup_request_id
                      JOIN users AS signup_user
                        ON signup_user.id=signup_request.user_id
                     WHERE outbox.delivery_type=%s
                       AND (
                           (outbox.status='pending' AND outbox.available_at <= %s)
                           OR (
                               outbox.status='processing'
                               AND outbox.claim_expires_at <= %s
                           )
                       )
                       AND signup_request.status='pending_email_verification'
                       AND signup_user.email_verified=FALSE
                       AND signup_user.is_active=FALSE
                     ORDER BY outbox.available_at, outbox.created_at, outbox.id
                     FOR UPDATE OF outbox SKIP LOCKED
                     LIMIT 1
                )
                UPDATE signup_verification_delivery_outbox AS outbox
                   SET status='processing',
                       lease_id=%s,
                       claimed_at=%s,
                       claim_expires_at=%s,
                       attempt_count=outbox.attempt_count + 1,
                       last_error_code=NULL,
                       updated_at=%s
                  FROM candidate,
                       signup_requests AS signup_request,
                       users AS signup_user
                 WHERE outbox.id=candidate.id
                   AND signup_request.id=outbox.signup_request_id
                   AND signup_user.id=signup_request.user_id
                RETURNING outbox.id,
                          outbox.signup_request_id,
                          signup_user.email,
                          outbox.attempt_count
                """,
                [
                    SIGNUP_VERIFICATION_DELIVERY_TYPE,
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
        return SignupVerificationDeliveryClaim(
            outbox_id=str(row[0]),
            signup_request_id=str(row[1]),
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
    ) -> SignupVerificationLockedDeliveryTarget | None:
        with connections[self.alias].cursor() as cursor:
            cursor.execute(
                """
                SELECT signup_request.id, signup_user.email
                  FROM signup_verification_delivery_outbox AS outbox
                  JOIN signup_requests AS signup_request
                    ON signup_request.id=outbox.signup_request_id
                  JOIN users AS signup_user
                    ON signup_user.id=signup_request.user_id
                 WHERE outbox.id=%s
                   AND outbox.delivery_type=%s
                   AND outbox.status='processing'
                   AND outbox.lease_id=%s
                   AND outbox.claim_expires_at > %s
                   AND signup_request.status='pending_email_verification'
                   AND signup_user.email_verified=FALSE
                   AND signup_user.is_active=FALSE
                 FOR UPDATE OF outbox, signup_request, signup_user
                """,
                [
                    outbox_id,
                    SIGNUP_VERIFICATION_DELIVERY_TYPE,
                    lease_id,
                    now,
                ],
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return SignupVerificationLockedDeliveryTarget(
            signup_request_id=str(row[0]),
            email=str(row[1]),
        )

    def mark_delivered(
        self,
        *,
        outbox_id: str,
        lease_id: str,
        delivered_at: datetime,
    ) -> bool:
        with connections[self.alias].cursor() as cursor:
            cursor.execute(
                """
                UPDATE signup_verification_delivery_outbox
                   SET status='delivered',
                       lease_id=NULL,
                       claimed_at=NULL,
                       claim_expires_at=NULL,
                       delivered_at=%s,
                       last_error_code=NULL,
                       updated_at=%s
                 WHERE id=%s
                   AND delivery_type=%s
                   AND status='processing'
                   AND lease_id=%s
                """,
                [
                    delivered_at,
                    delivered_at,
                    outbox_id,
                    SIGNUP_VERIFICATION_DELIVERY_TYPE,
                    lease_id,
                ],
            )
            return cursor.rowcount == 1

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
                UPDATE signup_verification_delivery_outbox
                   SET status='pending',
                       available_at=%s,
                       lease_id=NULL,
                       claimed_at=NULL,
                       claim_expires_at=NULL,
                       delivered_at=NULL,
                       last_error_code=%s,
                       updated_at=%s
                 WHERE id=%s
                   AND delivery_type=%s
                   AND status='processing'
                   AND lease_id=%s
                """,
                [
                    retry_at,
                    error_code,
                    failed_at,
                    outbox_id,
                    SIGNUP_VERIFICATION_DELIVERY_TYPE,
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
        with connections[self.alias].cursor() as cursor:
            cursor.execute(
                """
                UPDATE signup_verification_delivery_outbox
                   SET status='cancelled',
                       lease_id=NULL,
                       claimed_at=NULL,
                       claim_expires_at=NULL,
                       delivered_at=NULL,
                       last_error_code=%s,
                       updated_at=%s
                 WHERE id=%s
                   AND delivery_type=%s
                   AND status='processing'
                   AND lease_id=%s
                """,
                [
                    error_code,
                    cancelled_at,
                    outbox_id,
                    SIGNUP_VERIFICATION_DELIVERY_TYPE,
                    lease_id,
                ],
            )
            return cursor.rowcount == 1
