from __future__ import annotations

from dataclasses import dataclass

from django import VERSION as DJANGO_VERSION


APPROVED_DJANGO_SERIES = (5, 2)
MINIMUM_DJANGO_SECURITY_VERSION = (5, 2, 16)


@dataclass(frozen=True)
class DjangoSecurityBaseline:
    ready: bool
    code: str = "django_security_baseline"
    message: str = ""


def inspect_django_security_baseline(*, version=DJANGO_VERSION) -> DjangoSecurityBaseline:
    normalized = tuple(int(part) for part in version[:3])
    series_ok = normalized[:2] == APPROVED_DJANGO_SERIES
    patch_ok = normalized >= MINIMUM_DJANGO_SECURITY_VERSION
    if series_ok and patch_ok:
        return DjangoSecurityBaseline(
            ready=True,
            message="Django is on the approved 5.2 LTS security patch baseline.",
        )
    return DjangoSecurityBaseline(
        ready=False,
        message=(
            "Upgrade Django to the approved 5.2 LTS security patch baseline "
            "before release."
        ),
    )
