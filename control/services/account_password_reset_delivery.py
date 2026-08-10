from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable
from urllib.parse import urlencode, urlsplit, urlunsplit

from django.conf import settings
from django.core.mail import get_connection, send_mail
from django.views.decorators.debug import sensitive_variables


class AccountPasswordResetConfigurationError(RuntimeError):
    pass


class AccountPasswordResetEmailDeliveryError(RuntimeError):
    """Sanitized delivery failure; recipient and raw reset token stay private."""


@dataclass(frozen=True)
class AccountPasswordResetDeliveryConfig:
    reset_url: str
    token_ttl: timedelta
    request_cooldown: timedelta
    lease_for: timedelta
    retry_delay: timedelta
    email_timeout: timedelta
    max_attempts: int


def validate_account_password_reset_url(reset_url: str) -> None:
    if not isinstance(reset_url, str) or not reset_url.strip():
        raise ValueError("password reset URL is required")
    parts = urlsplit(reset_url.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError("password reset URL must be an absolute HTTP URL")
    if parts.fragment:
        raise ValueError("password reset URL must not contain a fragment")


@sensitive_variables("token")
def build_account_password_reset_link(reset_url: str, token: str) -> str:
    validate_account_password_reset_url(reset_url)
    if not isinstance(token, str) or not token:
        raise ValueError("password reset token is required")
    parts = urlsplit(reset_url.strip())
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            parts.query,
            urlencode({"token": token}),
        )
    )


@sensitive_variables(
    "to_email",
    "reset_link",
    "recipient",
    "body",
    "connection",
)
def send_account_password_reset_email(
    *,
    to_email: str,
    reset_link: str,
    expires_at: datetime,
    mail_sender: Callable = send_mail,
    connection_factory: Callable = get_connection,
    email_timeout_seconds: int | None = None,
    settings_obj=settings,
) -> None:
    recipient = str(to_email or "").strip()
    if not recipient:
        raise ValueError("recipient email is required")
    if not isinstance(expires_at, datetime):
        raise ValueError("password reset expiry is required")
    if (
        email_timeout_seconds is not None
        and (
            isinstance(email_timeout_seconds, bool)
            or not isinstance(email_timeout_seconds, int)
            or email_timeout_seconds <= 0
        )
    ):
        raise ValueError("email timeout must be a positive integer")
    validate_account_password_reset_url(reset_link.split("#", 1)[0])

    subject = "[GeoFlow] 비밀번호 재설정 안내"
    body = (
        "안녕하세요.\n\n"
        "GeoFlow 계정의 비밀번호 재설정 요청이 접수되었습니다.\n"
        "아래 링크를 이용해 새 비밀번호를 설정해 주세요.\n"
        "이 링크는 제한된 시간 동안 한 번만 사용할 수 있습니다.\n\n"
        f"{reset_link}\n\n"
        "본인이 요청하지 않은 경우 이 메일을 무시하셔도 됩니다.\n"
    )
    sender = (
        (os.environ.get("DEFAULT_FROM_EMAIL") or "").strip()
        or str(getattr(settings_obj, "DEFAULT_FROM_EMAIL", "no-reply@geoflow.local")).strip()
    )
    connection = None
    if email_timeout_seconds is not None:
        connection = connection_factory(timeout=email_timeout_seconds)
    send_kwargs = {"fail_silently": False}
    if connection is not None:
        send_kwargs["connection"] = connection

    try:
        sent_count = mail_sender(
            subject,
            body,
            sender,
            [recipient],
            **send_kwargs,
        )
    except Exception:
        raise AccountPasswordResetEmailDeliveryError(
            "password reset email delivery failed"
        ) from None
    if sent_count != 1:
        raise AccountPasswordResetEmailDeliveryError(
            "password reset email delivery failed"
        )


def load_account_password_reset_delivery_config(
    *,
    settings_obj=settings,
    environ: Mapping[str, str] = os.environ,
) -> AccountPasswordResetDeliveryConfig:
    reset_url = _setting_or_env(settings_obj, environ, "PASSWORD_RESET_URL")
    if not reset_url:
        verification_url = _setting_or_env(
            settings_obj,
            environ,
            "SIGNUP_EMAIL_VERIFICATION_URL",
        )
        if isinstance(verification_url, str) and verification_url.strip():
            parts = urlsplit(verification_url.strip())
            if parts.scheme in ("http", "https") and parts.netloc:
                reset_url = urlunsplit(
                    (parts.scheme, parts.netloc, "/password/reset/", "", "")
                )
    if not reset_url:
        site_origin_value = _setting_or_env(
            settings_obj,
            environ,
            "SITE_ORIGIN",
        )
        site_origin = str(site_origin_value or "").strip().rstrip("/")
        if site_origin:
            reset_url = f"{site_origin}/password/reset/"
    if not isinstance(reset_url, str):
        raise AccountPasswordResetConfigurationError("password reset URL is unavailable")
    try:
        validate_account_password_reset_url(reset_url)
    except ValueError:
        raise AccountPasswordResetConfigurationError(
            "password reset URL configuration is invalid"
        ) from None

    ttl_seconds = _int_setting_or_env(
        settings_obj, environ, "PASSWORD_RESET_TTL_SECONDS", default=3600
    )
    cooldown_seconds = _int_setting_or_env(
        settings_obj, environ, "PASSWORD_RESET_REQUEST_COOLDOWN_SECONDS", default=600
    )
    lease_seconds = _int_setting_or_env(
        settings_obj,
        environ,
        "PASSWORD_RESET_OUTBOX_LEASE_SECONDS",
        default=_coerce_int(
            getattr(settings_obj, "SIGNUP_EMAIL_VERIFICATION_OUTBOX_LEASE_SECONDS", None),
            120,
        ),
    )
    retry_seconds = _int_setting_or_env(
        settings_obj,
        environ,
        "PASSWORD_RESET_OUTBOX_RETRY_SECONDS",
        default=_coerce_int(
            getattr(settings_obj, "SIGNUP_EMAIL_VERIFICATION_OUTBOX_RETRY_SECONDS", None),
            300,
        ),
    )
    email_timeout_seconds = _int_setting_or_env(
        settings_obj,
        environ,
        "EMAIL_TIMEOUT",
        default=30,
    )
    max_attempts = _int_setting_or_env(
        settings_obj,
        environ,
        "PASSWORD_RESET_OUTBOX_MAX_ATTEMPTS",
        default=_coerce_int(
            getattr(settings_obj, "SIGNUP_EMAIL_VERIFICATION_OUTBOX_MAX_ATTEMPTS", None),
            5,
        ),
    )

    ttl_seconds = _require_range(ttl_seconds, 300, 24 * 60 * 60, "token ttl")
    cooldown_seconds = _require_range(cooldown_seconds, 60, 24 * 60 * 60, "request cooldown")
    lease_seconds = _require_range(lease_seconds, 30, 60 * 60, "outbox lease")
    retry_seconds = _require_range(retry_seconds, 60, 24 * 60 * 60, "outbox retry")
    email_timeout_seconds = _require_range(email_timeout_seconds, 1, 60 * 60, "email timeout")
    max_attempts = _require_range(max_attempts, 1, 20, "max attempts")
    if lease_seconds <= email_timeout_seconds:
        raise AccountPasswordResetConfigurationError(
            "password reset outbox lease must exceed email timeout"
        )

    return AccountPasswordResetDeliveryConfig(
        reset_url=reset_url.strip(),
        token_ttl=timedelta(seconds=ttl_seconds),
        request_cooldown=timedelta(seconds=cooldown_seconds),
        lease_for=timedelta(seconds=lease_seconds),
        retry_delay=timedelta(seconds=retry_seconds),
        email_timeout=timedelta(seconds=email_timeout_seconds),
        max_attempts=max_attempts,
    )


def _setting_or_env(settings_obj, environ, name: str):
    value = environ.get(name)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return getattr(settings_obj, name, None)


def _int_setting_or_env(settings_obj, environ, name: str, *, default: int) -> int:
    value = _setting_or_env(settings_obj, environ, name)
    if value is None or value == "":
        return default
    return _coerce_int(value, default=None)


def _coerce_int(value, default):
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


def _require_range(value, minimum: int, maximum: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise AccountPasswordResetConfigurationError(
            f"password reset {label} configuration is invalid"
        )
    return value
