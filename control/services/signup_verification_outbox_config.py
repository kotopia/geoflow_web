from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings

from .signup_verification_delivery import validate_signup_email_verification_url
from .signup_verification_outbox_feature import (
    signup_verification_outbox_enabled,
)
from .signup_verification_service import EmailVerificationConfigurationError


@dataclass(frozen=True)
class SignupVerificationOutboxConfig:
    verification_url: str
    token_ttl: timedelta
    lease_for: timedelta
    retry_delay: timedelta
    email_timeout: timedelta


def load_signup_verification_outbox_config(
    *,
    settings_obj=settings,
    environ: Mapping[str, str] = os.environ,
) -> SignupVerificationOutboxConfig:
    if not signup_verification_outbox_enabled(
        settings_obj=settings_obj,
        environ=environ,
    ):
        raise EmailVerificationConfigurationError(
            "signup verification outbox is disabled"
        )

    verification_url = _setting_or_env(
        settings_obj,
        environ,
        "SIGNUP_EMAIL_VERIFICATION_URL",
    )
    ttl_seconds = _setting_or_env_int(
        settings_obj,
        environ,
        "SIGNUP_EMAIL_VERIFICATION_TTL_SECONDS",
    )
    lease_seconds = _setting_or_env_int(
        settings_obj,
        environ,
        "SIGNUP_EMAIL_VERIFICATION_OUTBOX_LEASE_SECONDS",
    )
    retry_seconds = _setting_or_env_int(
        settings_obj,
        environ,
        "SIGNUP_EMAIL_VERIFICATION_OUTBOX_RETRY_SECONDS",
    )
    email_timeout_seconds = _setting_or_env_int(
        settings_obj,
        environ,
        "EMAIL_TIMEOUT",
    )

    if not isinstance(verification_url, str) or not verification_url.strip():
        raise EmailVerificationConfigurationError(
            "signup verification URL configuration is invalid"
        )
    try:
        validate_signup_email_verification_url(verification_url.strip())
    except ValueError:
        raise EmailVerificationConfigurationError(
            "signup verification URL configuration is invalid"
        ) from None

    ttl_seconds = _require_seconds(
        ttl_seconds,
        name="token ttl",
        minimum=60,
        maximum=7 * 24 * 60 * 60,
    )
    lease_seconds = _require_seconds(
        lease_seconds,
        name="outbox lease",
        minimum=30,
        maximum=60 * 60,
    )
    retry_seconds = _require_seconds(
        retry_seconds,
        name="outbox retry",
        minimum=60,
        maximum=24 * 60 * 60,
    )
    email_timeout_seconds = _require_seconds(
        email_timeout_seconds,
        name="email timeout",
        minimum=1,
        maximum=60 * 60,
    )
    if lease_seconds <= email_timeout_seconds:
        raise EmailVerificationConfigurationError(
            "signup verification outbox lease must exceed email timeout"
        )
    return SignupVerificationOutboxConfig(
        verification_url=verification_url.strip(),
        token_ttl=timedelta(seconds=ttl_seconds),
        lease_for=timedelta(seconds=lease_seconds),
        retry_delay=timedelta(seconds=retry_seconds),
        email_timeout=timedelta(seconds=email_timeout_seconds),
    )


def _setting_or_env(settings_obj, environ, name: str):
    value = getattr(settings_obj, name, None)
    if value is not None:
        return value
    return environ.get(name)


def _setting_or_env_int(settings_obj, environ, name: str):
    value = _setting_or_env(settings_obj, environ, name)
    if value is None or isinstance(value, (bool, int)):
        return value
    if not isinstance(value, str):
        return value
    try:
        return int(value.strip())
    except ValueError:
        return value


def _require_seconds(value, *, name: str, minimum: int, maximum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise EmailVerificationConfigurationError(
            f"signup verification {name} configuration is invalid"
        )
    return value
