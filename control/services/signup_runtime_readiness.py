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
GMAIL_SMTP_HOST = "smtp.gmail.com"
GMAIL_SMTP_PORT = 587
SUPPORTED_SMTP_HOST_PORTS = {
    NAVER_SMTP_HOST: NAVER_SMTP_PORT,
    GMAIL_SMTP_HOST: GMAIL_SMTP_PORT,
}
EXPECTED_VERIFICATION_PATH = "/signup/verify/"


def _environment_or_setting_text(settings_obj, environ, name: str) -> str:
    """Use an explicit runtime environment value before a settings fallback.

    GeoFlow keeps local-development placeholders in settings.py. Production
    deployment values are supplied through the environment, so readiness checks
    must resolve configuration in the same order as the actual mail delivery path.
    """

    raw = environ.get(name)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    configured = getattr(settings_obj, name, None)
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    return ""


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
    site_origin = _environment_or_setting_text(
        settings_obj,
        environ,
        "SITE_ORIGIN",
    )
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
    sender = _environment_or_setting_text(
        settings_obj,
        environ,
        "DEFAULT_FROM_EMAIL",
    )
    port = getattr(settings_obj, "EMAIL_PORT", None)
    use_tls = getattr(settings_obj, "EMAIL_USE_TLS", False)

    if backend != SMTP_BACKEND:
        return False
    expected_port = SUPPORTED_SMTP_HOST_PORTS.get(host.lower())
    if expected_port is None:
        return False
    if isinstance(port, bool) or not isinstance(port, int) or port != expected_port:
        return False
    if not user or not password or not sender:
        return False
    if sender.endswith("@geoflow.local"):
        return False
    if use_tls is not True:
        return False
    return True
