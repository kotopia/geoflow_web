from __future__ import annotations

import os
from collections.abc import Mapping

from django.conf import settings


_TRUE_VALUES = {"1", "true", "yes", "y", "on"}


def signup_verification_outbox_enabled(
    *,
    settings_obj=settings,
    environ: Mapping[str, str] = os.environ,
) -> bool:
    """Return the server-owned delivery feature flag, defaulting safely to off."""

    configured = getattr(
        settings_obj,
        "ENABLE_SIGNUP_EMAIL_VERIFICATION_OUTBOX",
        None,
    )
    if configured is not None:
        return configured is True

    raw = environ.get("ENABLE_SIGNUP_EMAIL_VERIFICATION_OUTBOX")
    if not isinstance(raw, str):
        return False
    return raw.strip().lower() in _TRUE_VALUES
