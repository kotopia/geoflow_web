from __future__ import annotations

import os
from collections.abc import Mapping
from urllib.parse import urlsplit

from django.conf import settings

from .signup_verification_outbox_config import load_signup_verification_outbox_config
from .signup_verification_runtime import load_signup_email_verification_key_ring
from .signup_verification_service import EmailVerificationConfigurationError


SMTP_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
NAVER_SMTP_HOST = "smtp.naver.com"
NAVER_SMTP_PORT = 587
EXPECTED_VERIFICATION_PATH = "/signup/verify/"


def _setting_or_env_text(settings_obj, environ, name: str) -> str:
    configured = getattr(settings_obj, name, None)
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    raw = environ.get(name)
    return raw.strip() if isinstance(raw, str) and raw.strip() else ""


def _origin(parts) -> tuple[str, str]:
    return (parts.scheme.lower(), parts.netloc.lower())


def signup_public_runtime_ready(
    *,
    settings_obj=settings,
    environ: Mapping[str, str] = os.environ,
) -> bool:
    """Fail closed unless signup verification and SMTP runtime are configured.

    This function validates only configuration shape/presence. It does not send mail,
    open a database connection, or expose credential/key values.
    """

    try:
        outbox_config = load_signup_verification_outbox_config(
            settings_obj=settings_obj,
            environ=environ,
        )
        load_signup_email_verification_key_ring(settings_obj=settings_obj)
    except (EmailVerificationConfigurationError, ValueError, TypeError):
        return False

    verification_parts = urlsplit(outbox_config.verification_url)
    site_origin = _setting_or_env_text(settings_obj, environ, "SITE_ORIGIN")
    site_parts = urlsplit(site_origin)
    if site_parts.scheme not in ("http", "https") or not site_parts.netloc:
        return False
    if (
        site_parts.path not in ("", "/")
        or site_parts.query
        or site_parts.fragment
        or site_parts.username
        or site_parts.password
    ):
        return False
    if verification_parts.username or verification_parts.password:
        return False
    if _origin(verification_parts) != _origin(site_parts):
        return False
    if verification_parts.path != EXPECTED_VERIFICATION_PATH:
        return False
    if verification_parts.query or verification_parts.fragment:
        return False
    if not getattr(settings_obj, "DEBUG", False):
        if verification_parts.scheme != "https" or site_parts.scheme != "https":
            return False

    backend = str(getattr(settings_obj, "EMAIL_BACKEND", "")).strip()
    host = str(getattr(settings_obj, "EMAIL_HOST", "")).strip()
    user = str(getattr(settings_obj, "EMAIL_HOST_USER", "")).strip()
    password = str(getattr(settings_obj, "EMAIL_HOST_PASSWORD", "")).strip()
    sender = str(getattr(settings_obj, "DEFAULT_FROM_EMAIL", "")).strip()
    port = getattr(settings_obj, "EMAIL_PORT", None)
    use_tls = getattr(settings_obj, "EMAIL_USE_TLS", False)

    if backend != SMTP_BACKEND:
        return False
    if host.lower() != NAVER_SMTP_HOST:
        return False
    if isinstance(port, bool) or not isinstance(port, int) or port != NAVER_SMTP_PORT:
        return False
    if not user or not password or not sender:
        return False
    if sender.endswith("@geoflow.local"):
        return False
    if use_tls is not True:
        return False
    return True
