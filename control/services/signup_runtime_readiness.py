from __future__ import annotations

import os
from collections.abc import Mapping

from django.conf import settings

from .signup_verification_outbox_config import load_signup_verification_outbox_config
from .signup_verification_runtime import load_signup_email_verification_key_ring
from .signup_verification_service import EmailVerificationConfigurationError


SMTP_BACKEND = "django.core.mail.backends.smtp.EmailBackend"


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
        load_signup_verification_outbox_config(
            settings_obj=settings_obj,
            environ=environ,
        )
        load_signup_email_verification_key_ring(settings_obj=settings_obj)
    except (EmailVerificationConfigurationError, ValueError, TypeError):
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
    if not host or host == "smtp.example.com":
        return False
    if isinstance(port, bool) or not isinstance(port, int) or port <= 0:
        return False
    if not user or not password or not sender:
        return False
    if sender.endswith("@geoflow.local"):
        return False
    if use_tls is not True:
        return False
    return True
