from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable

from django.conf import settings
from django.views.decorators.debug import sensitive_variables

from .signup_email_verification_signup_service import (
    create_signup_request_with_verification_token,
)
from .signup_service import SignupRequestInput
from .signup_verification_outbox_feature import (
    signup_verification_outbox_enabled,
)
from .signup_verification_delivery import (
    build_signup_email_verification_link,
    validate_signup_email_verification_url,
)
from .signup_verification_email_delivery import (
    SignupVerificationEmailDeliveryError,
    send_signup_email_verification_email,
)
from .signup_verification_runtime import (
    load_signup_email_verification_key_ring,
)
from .signup_verification_service import EmailVerificationConfigurationError


logger = logging.getLogger(__name__)
_MINIMUM_TTL_SECONDS = 60
_MAXIMUM_TTL_SECONDS = 7 * 24 * 60 * 60


@dataclass(frozen=True)
class SignupSubmissionOutcome:
    delivery_succeeded: bool


def load_signup_email_verification_ttl(
    *,
    settings_obj=settings,
) -> timedelta:
    value = getattr(
        settings_obj,
        "SIGNUP_EMAIL_VERIFICATION_TTL_SECONDS",
        None,
    )
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not _MINIMUM_TTL_SECONDS <= value <= _MAXIMUM_TTL_SECONDS
    ):
        raise EmailVerificationConfigurationError(
            "signup email verification ttl configuration is invalid"
        )
    return timedelta(seconds=value)


@sensitive_variables(
    "data",
    "key_ring",
    "pending",
    "verification_link",
)
def submit_signup_with_email_verification(
    data: SignupRequestInput,
    *,
    verification_url: str,
    settings_obj=settings,
    create_pending: Callable = create_signup_request_with_verification_token,
    link_builder: Callable = build_signup_email_verification_link,
    deliver: Callable = send_signup_email_verification_email,
) -> SignupSubmissionOutcome:
    """Persist signup and token first, then cross the email delivery boundary."""

    if signup_verification_outbox_enabled(settings_obj=settings_obj):
        raise EmailVerificationConfigurationError(
            "synchronous signup verification delivery is disabled while outbox is enabled"
        )

    validate_signup_email_verification_url(verification_url)
    key_ring = load_signup_email_verification_key_ring(
        settings_obj=settings_obj,
    )
    ttl = load_signup_email_verification_ttl(settings_obj=settings_obj)
    pending = create_pending(
        data,
        ttl=ttl,
        key_ring=key_ring,
    )
    verification_link = link_builder(
        verification_url,
        pending.token,
    )

    try:
        deliver(
            to_email=data.email,
            verification_link=verification_link,
            expires_at=pending.expires_at,
            settings_obj=settings_obj,
        )
    except SignupVerificationEmailDeliveryError:
        logger.warning("SIGNUP: verification email delivery failed")
        return SignupSubmissionOutcome(delivery_succeeded=False)

    return SignupSubmissionOutcome(delivery_succeeded=True)
