from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from django.conf import settings
from django.db import connections


@dataclass(frozen=True)
class PendingSignupReviewListItem:
    signup_request_id: str = field(repr=False)
    user_id: str = field(repr=False)
    email: str = field(repr=False)
    name_display: str = field(repr=False)
    organization_name: str | None = field(repr=False)
    version: int
    submitted_at: datetime
    verified_at: datetime | None


@dataclass(frozen=True)
class PendingSignupReviewDetail:
    signup_request_id: str = field(repr=False)
    user_id: str = field(repr=False)
    email: str = field(repr=False)
    name_display: str = field(repr=False)
    contact_phone: str | None = field(repr=False)
    organization_name: str | None = field(repr=False)
    signup_purpose: str = field(repr=False)
    terms_version: str
    terms_accepted_at: datetime
    privacy_version: str
    privacy_accepted_at: datetime
    version: int
    submitted_at: datetime
    verified_at: datetime | None


class SignupReviewQueryRepository(Protocol):
    alias: str

    def list_pending_approval(
        self,
        *,
        limit: int,
        offset: int,
    ) -> tuple[PendingSignupReviewListItem, ...]: ...

    def get_pending_approval(
        self,
        *,
        signup_request_id: str,
    ) -> PendingSignupReviewDetail | None: ...


class CentralSignupReviewQueryRepository:
    def __init__(self, alias: str | None = None):
        self.alias = alias or getattr(settings, "CENTRAL_DB_ALIAS", "default")

    def list_pending_approval(
        self,
        *,
        limit: int,
        offset: int,
    ) -> tuple[PendingSignupReviewListItem, ...]:
        with connections[self.alias].cursor() as cursor:
            cursor.execute(
                """
                SELECT signup_request.id,
                       signup_request.user_id,
                       signup_user.email,
                       signup_user.name_display,
                       signup_request.organization_name,
                       signup_request.version,
                       signup_request.submitted_at,
                       (
                           SELECT max(signup_event.created_at)
                             FROM signup_request_events AS signup_event
                            WHERE signup_event.signup_request_id=signup_request.id
                              AND signup_event.event_type='verified'
                       ) AS verified_at
                  FROM signup_requests AS signup_request
                  JOIN users AS signup_user
                    ON signup_user.id=signup_request.user_id
                 WHERE signup_request.status='pending_approval'
                   AND signup_user.email_verified=TRUE
                   AND signup_user.is_active=FALSE
                 ORDER BY signup_request.submitted_at, signup_request.id
                 LIMIT %s OFFSET %s
                """,
                [limit, offset],
            )
            rows = cursor.fetchall()
        return tuple(_list_item_from_row(row) for row in rows)

    def get_pending_approval(
        self,
        *,
        signup_request_id: str,
    ) -> PendingSignupReviewDetail | None:
        with connections[self.alias].cursor() as cursor:
            cursor.execute(
                """
                SELECT signup_request.id,
                       signup_request.user_id,
                       signup_user.email,
                       signup_user.name_display,
                       signup_request.contact_phone,
                       signup_request.organization_name,
                       signup_request.signup_purpose,
                       signup_request.terms_version,
                       signup_request.terms_accepted_at,
                       signup_request.privacy_version,
                       signup_request.privacy_accepted_at,
                       signup_request.version,
                       signup_request.submitted_at,
                       (
                           SELECT max(signup_event.created_at)
                             FROM signup_request_events AS signup_event
                            WHERE signup_event.signup_request_id=signup_request.id
                              AND signup_event.event_type='verified'
                       ) AS verified_at
                  FROM signup_requests AS signup_request
                  JOIN users AS signup_user
                    ON signup_user.id=signup_request.user_id
                 WHERE signup_request.id=%s
                   AND signup_request.status='pending_approval'
                   AND signup_user.email_verified=TRUE
                   AND signup_user.is_active=FALSE
                 LIMIT 1
                """,
                [signup_request_id],
            )
            row = cursor.fetchone()
        return _detail_from_row(row) if row is not None else None


def list_pending_signup_reviews(
    *,
    limit: int = 50,
    offset: int = 0,
    repository: SignupReviewQueryRepository | None = None,
) -> tuple[PendingSignupReviewListItem, ...]:
    """Read a bounded review queue after the caller has enforced permission."""

    _validate_pagination(limit=limit, offset=offset)
    repository = repository or CentralSignupReviewQueryRepository()
    return repository.list_pending_approval(limit=limit, offset=offset)


def get_pending_signup_review(
    signup_request_id: str,
    *,
    repository: SignupReviewQueryRepository | None = None,
) -> PendingSignupReviewDetail | None:
    """Read one still-eligible review item after permission enforcement."""

    normalized_id = str(signup_request_id).strip()
    if not normalized_id:
        raise ValueError("signup_request_id is required")
    repository = repository or CentralSignupReviewQueryRepository()
    return repository.get_pending_approval(signup_request_id=normalized_id)


def _validate_pagination(*, limit: int, offset: int) -> None:
    if not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")
    if offset < 0 or offset > 100_000:
        raise ValueError("offset must be between 0 and 100000")


def _list_item_from_row(row) -> PendingSignupReviewListItem:
    return PendingSignupReviewListItem(
        signup_request_id=str(row[0]),
        user_id=str(row[1]),
        email=str(row[2]),
        name_display=str(row[3]),
        organization_name=row[4],
        version=int(row[5]),
        submitted_at=row[6],
        verified_at=row[7],
    )


def _detail_from_row(row) -> PendingSignupReviewDetail:
    return PendingSignupReviewDetail(
        signup_request_id=str(row[0]),
        user_id=str(row[1]),
        email=str(row[2]),
        name_display=str(row[3]),
        contact_phone=row[4],
        organization_name=row[5],
        signup_purpose=str(row[6]),
        terms_version=str(row[7]),
        terms_accepted_at=row[8],
        privacy_version=str(row[9]),
        privacy_accepted_at=row[10],
        version=int(row[11]),
        submitted_at=row[12],
        verified_at=row[13],
    )
