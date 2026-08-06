from __future__ import annotations

import re
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Literal, Protocol

from django.conf import settings
from django.db import connections, transaction
from django.utils import timezone


SignupDecision = Literal["approved", "rejected"]
_DECISION_REASON_RE = re.compile(r"^[a-z0-9_.-]{1,64}$")


class SignupAccountDecisionRejected(Exception):
    """Fail-closed conflict for stale, invalid, or ineligible decisions."""


@dataclass(frozen=True)
class SignupAccountDecision:
    signup_request_id: str
    expected_version: int
    actor_user_id: str
    decision: SignupDecision
    reason_code: str | None = None
    note: str | None = None


class SignupAccountDecisionRepository(Protocol):
    alias: str

    def apply_request_decision(
        self,
        *,
        decision: SignupAccountDecision,
        decided_at,
    ) -> str | None: ...

    def activate_verified_user(self, *, user_id: str, changed_at) -> bool: ...

    def append_decision_event(
        self,
        *,
        signup_request_id: str,
        actor_user_id: str,
        decision: SignupDecision,
        reason_code: str | None,
        note: str | None,
        created_at,
    ) -> None: ...


class CentralSignupAccountDecisionRepository:
    def __init__(self, alias: str | None = None):
        self.alias = alias or getattr(settings, "CENTRAL_DB_ALIAS", "default")

    def apply_request_decision(
        self,
        *,
        decision: SignupAccountDecision,
        decided_at,
    ) -> str | None:
        with connections[self.alias].cursor() as cursor:
            cursor.execute(
                """
                UPDATE signup_requests AS signup_request
                   SET status=%s,
                       decided_at=%s,
                       decided_by_user_id=%s,
                       decision_reason_code=%s,
                       decision_note=%s,
                       version=version + 1,
                       updated_at=%s
                  FROM users AS signup_user
                 WHERE signup_request.user_id=signup_user.id
                   AND signup_request.id=%s
                   AND signup_request.status='pending_approval'
                   AND signup_request.version=%s
                   AND signup_user.email_verified=TRUE
                   AND signup_user.is_active=FALSE
                RETURNING signup_request.user_id
                """,
                [
                    decision.decision,
                    decided_at,
                    decision.actor_user_id,
                    decision.reason_code,
                    decision.note,
                    decided_at,
                    decision.signup_request_id,
                    decision.expected_version,
                ],
            )
            row = cursor.fetchone()
        return str(row[0]) if row is not None else None

    def activate_verified_user(self, *, user_id: str, changed_at) -> bool:
        with connections[self.alias].cursor() as cursor:
            cursor.execute(
                """
                UPDATE users
                   SET is_active=TRUE, updated_at=%s
                 WHERE id=%s
                   AND email_verified=TRUE
                   AND is_active=FALSE
                """,
                [changed_at, user_id],
            )
            return cursor.rowcount == 1

    def append_decision_event(
        self,
        *,
        signup_request_id: str,
        actor_user_id: str,
        decision: SignupDecision,
        reason_code: str | None,
        note: str | None,
        created_at,
    ) -> None:
        with connections[self.alias].cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO signup_request_events (
                    id, signup_request_id, event_type, from_status,
                    to_status, actor_user_id, reason_code, note, created_at
                ) VALUES (
                    gen_random_uuid(), %s, %s, 'pending_approval',
                    %s, %s, %s, %s, %s
                )
                """,
                [
                    signup_request_id,
                    decision,
                    decision,
                    actor_user_id,
                    reason_code,
                    note,
                    created_at,
                ],
            )


def decide_signup_account(
    decision: SignupAccountDecision,
    *,
    repository: SignupAccountDecisionRepository | None = None,
    atomic_context: AbstractContextManager | None = None,
) -> None:
    """Apply one optimistic account decision in a central transaction."""

    normalized = _normalize_decision(decision)
    repository = repository or CentralSignupAccountDecisionRepository()
    alias = getattr(repository, "alias", getattr(settings, "CENTRAL_DB_ALIAS", "default"))
    context = atomic_context or transaction.atomic(using=alias)

    decided_at = timezone.now()
    with context:
        user_id = repository.apply_request_decision(
            decision=normalized,
            decided_at=decided_at,
        )
        if user_id is None:
            raise SignupAccountDecisionRejected(
                "signup account decision could not be applied"
            )

        if normalized.decision == "approved":
            if not repository.activate_verified_user(
                user_id=user_id,
                changed_at=decided_at,
            ):
                raise SignupAccountDecisionRejected(
                    "signup account activation could not be applied"
                )

        repository.append_decision_event(
            signup_request_id=normalized.signup_request_id,
            actor_user_id=normalized.actor_user_id,
            decision=normalized.decision,
            reason_code=normalized.reason_code,
            note=normalized.note,
            created_at=decided_at,
        )


def _normalize_decision(decision: SignupAccountDecision) -> SignupAccountDecision:
    if decision.decision not in ("approved", "rejected"):
        raise ValueError("decision must be approved or rejected")
    if decision.expected_version < 1:
        raise ValueError("expected_version must be positive")
    if not str(decision.signup_request_id).strip():
        raise ValueError("signup_request_id is required")
    if not str(decision.actor_user_id).strip():
        raise ValueError("actor_user_id is required")

    reason_code = _optional_text(decision.reason_code)
    if reason_code is not None and not _DECISION_REASON_RE.fullmatch(reason_code):
        raise ValueError("reason_code must use a bounded machine-readable format")

    note = _optional_text(decision.note)
    if note is not None:
        if len(note) > 1000:
            raise ValueError("note must contain at most 1000 characters")
        if any(ord(character) < 32 and character not in "\t\n\r" for character in note):
            raise ValueError("note contains unsupported control characters")

    return SignupAccountDecision(
        signup_request_id=str(decision.signup_request_id).strip(),
        expected_version=decision.expected_version,
        actor_user_id=str(decision.actor_user_id).strip(),
        decision=decision.decision,
        reason_code=reason_code,
        note=note,
    )


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
