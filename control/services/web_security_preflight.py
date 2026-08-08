from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings


CANONICAL_PRODUCTION_ORIGIN = "https://geoflow.co.kr"
SAFE_REFERRER_POLICIES = {
    "no-referrer",
    "same-origin",
    "strict-origin",
    "strict-origin-when-cross-origin",
}
SAFE_FRAME_OPTIONS = {"deny", "sameorigin"}
REQUIRED_SECURITY_MIDDLEWARE = {
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
}


@dataclass(frozen=True)
class WebSecurityCheck:
    code: str
    ready: bool
    message: str


def inspect_web_security_baseline(*, settings_obj=settings) -> tuple[WebSecurityCheck, ...]:
    """Inspect browser-facing Django security settings without any external I/O."""

    checks: list[WebSecurityCheck] = []

    middleware = set(getattr(settings_obj, "MIDDLEWARE", ()) or ())
    middleware_ready = REQUIRED_SECURITY_MIDDLEWARE.issubset(middleware)
    checks.append(
        WebSecurityCheck(
            code="security_middleware",
            ready=middleware_ready,
            message=(
                "Required Django security middleware is installed."
                if middleware_ready
                else "Keep Django security, CSRF, and clickjacking middleware enabled."
            ),
        )
    )

    trusted_origins = {
        str(value).strip().rstrip("/")
        for value in (getattr(settings_obj, "CSRF_TRUSTED_ORIGINS", ()) or ())
        if str(value).strip()
    }
    csrf_origin_ready = CANONICAL_PRODUCTION_ORIGIN in trusted_origins
    checks.append(
        WebSecurityCheck(
            code="csrf_canonical_origin",
            ready=csrf_origin_ready,
            message=(
                "Canonical production origin is explicitly trusted for CSRF."
                if csrf_origin_ready
                else "Add the canonical HTTPS production origin to CSRF_TRUSTED_ORIGINS."
            ),
        )
    )

    nosniff_ready = getattr(settings_obj, "SECURE_CONTENT_TYPE_NOSNIFF", True) is True
    checks.append(
        WebSecurityCheck(
            code="content_type_nosniff",
            ready=nosniff_ready,
            message=(
                "MIME sniffing protection is enabled."
                if nosniff_ready
                else "Enable SECURE_CONTENT_TYPE_NOSNIFF."
            ),
        )
    )

    referrer_policy = str(
        getattr(settings_obj, "SECURE_REFERRER_POLICY", "same-origin") or ""
    ).strip().lower()
    referrer_ready = referrer_policy in SAFE_REFERRER_POLICIES
    checks.append(
        WebSecurityCheck(
            code="referrer_policy",
            ready=referrer_ready,
            message=(
                "A restrictive referrer policy is configured."
                if referrer_ready
                else "Use a restrictive production SECURE_REFERRER_POLICY."
            ),
        )
    )

    frame_option = str(
        getattr(settings_obj, "X_FRAME_OPTIONS", "DENY") or ""
    ).strip().lower()
    frame_ready = frame_option in SAFE_FRAME_OPTIONS
    checks.append(
        WebSecurityCheck(
            code="frame_options",
            ready=frame_ready,
            message=(
                "Clickjacking protection is enabled."
                if frame_ready
                else "Use DENY or SAMEORIGIN for X_FRAME_OPTIONS."
            ),
        )
    )

    return tuple(checks)
