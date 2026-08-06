from __future__ import annotations

from base64 import b64decode
from collections.abc import Mapping

from django.conf import settings

from .signup_verification_service import EmailVerificationConfigurationError
from .signup_verification_token_service import (
    HmacSha256VerificationKeyRing,
    verify_signup_email_with_database_token,
)


def load_signup_email_verification_key_ring(
    *,
    settings_obj=settings,
) -> HmacSha256VerificationKeyRing:
    """Load a versioned HMAC key ring without exposing key material."""

    active_key_id = getattr(
        settings_obj,
        "SIGNUP_EMAIL_VERIFICATION_ACTIVE_KEY_ID",
        None,
    )
    configured_keys = getattr(
        settings_obj,
        "SIGNUP_EMAIL_VERIFICATION_HMAC_KEYS",
        None,
    )
    if not isinstance(active_key_id, str) or not active_key_id:
        raise EmailVerificationConfigurationError(
            "signup email verification key configuration is unavailable"
        )
    if not isinstance(configured_keys, Mapping) or not configured_keys:
        raise EmailVerificationConfigurationError(
            "signup email verification key configuration is unavailable"
        )

    decoded_keys: dict[str, bytes] = {}
    try:
        for key_id, encoded_key in configured_keys.items():
            if not isinstance(key_id, str) or not isinstance(encoded_key, str):
                raise ValueError("invalid key configuration")
            decoded_keys[key_id] = b64decode(
                encoded_key.encode("ascii"),
                altchars=b"-_",
                validate=True,
            )
        return HmacSha256VerificationKeyRing(
            active_key_id=active_key_id,
            keys=decoded_keys,
        )
    except (UnicodeEncodeError, ValueError) as exc:
        raise EmailVerificationConfigurationError(
            "signup email verification key configuration is invalid"
        ) from exc


def verify_signup_email_from_runtime_config(
    token: str,
    *,
    settings_obj=settings,
) -> None:
    key_ring = load_signup_email_verification_key_ring(
        settings_obj=settings_obj,
    )
    verify_signup_email_with_database_token(
        token,
        key_ring=key_ring,
    )
