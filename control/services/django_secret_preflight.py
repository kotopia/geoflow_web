from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings


MINIMUM_SECRET_KEY_LENGTH = 50
INSECURE_SECRET_PREFIX = "django-insecure-"


@dataclass(frozen=True)
class DjangoSecretKeyCheck:
    code: str
    ready: bool
    message: str


def inspect_django_secret_key(*, settings_obj=settings) -> DjangoSecretKeyCheck:
    """Validate secret-key shape without ever returning or logging the key value."""

    value = str(getattr(settings_obj, "SECRET_KEY", "") or "")
    ready = bool(
        len(value) >= MINIMUM_SECRET_KEY_LENGTH
        and not value.startswith(INSECURE_SECRET_PREFIX)
    )
    return DjangoSecretKeyCheck(
        code="django_secret_key",
        ready=ready,
        message=(
            "Django secret key meets the production shape baseline."
            if ready
            else "Use a production Django secret key of at least 50 characters and not the development prefix."
        ),
    )
