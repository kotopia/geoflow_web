from __future__ import annotations

from typing import Protocol

from django.conf import settings
from django.db import connections


class LegacyPasswordSetupSignupConflict(Exception):
    """The legacy password setup flow must not mutate an open signup account."""


class LegacyPasswordSetupCompatibilityRepository(Protocol):
    alias: str

    def has_open_signup_request(self, *, user_id: str) -> bool: ...


class CentralLegacyPasswordSetupCompatibilityRepository:
    def __init__(self, alias: str | None = None):
        self.alias = alias or getattr(settings, "CENTRAL_DB_ALIAS", "default")

    def has_open_signup_request(self, *, user_id: str) -> bool:
        with connections[self.alias].cursor() as cursor:
            cursor.execute(
                """
                SELECT 1
                  FROM signup_requests
                 WHERE user_id=%s
                   AND status IN (
                       'pending_email_verification',
                       'pending_approval'
                   )
                 LIMIT 1
                """,
                [user_id],
            )
            return cursor.fetchone() is not None


def require_legacy_password_setup_compatible(
    user_id: str,
    *,
    repository: LegacyPasswordSetupCompatibilityRepository | None = None,
) -> None:
    """Fail closed when a legacy password token targets an open signup request."""

    normalized_user_id = str(user_id).strip()
    if not normalized_user_id:
        raise ValueError("user_id is required")

    repository = repository or CentralLegacyPasswordSetupCompatibilityRepository()
    if repository.has_open_signup_request(user_id=normalized_user_id):
        raise LegacyPasswordSetupSignupConflict(
            "legacy password setup is not available for an open signup request"
        )
