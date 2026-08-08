from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings


SAFE_SAMESITE_VALUES = {"lax", "strict"}


@dataclass(frozen=True)
class SessionSecurityCheck:
    code: str
    ready: bool
    message: str


def inspect_session_security_baseline(*, settings_obj=settings) -> tuple[SessionSecurityCheck, ...]:
    """Check cookie/session policy only; this performs no I/O or secret access."""

    checks: list[SessionSecurityCheck] = []

    session_httponly = getattr(settings_obj, "SESSION_COOKIE_HTTPONLY", True) is True
    checks.append(
        SessionSecurityCheck(
            code="session_cookie_httponly",
            ready=session_httponly,
            message=(
                "Session cookie is HttpOnly."
                if session_httponly
                else "Require HttpOnly on the session cookie."
            ),
        )
    )

    session_samesite = str(
        getattr(settings_obj, "SESSION_COOKIE_SAMESITE", "Lax") or ""
    ).strip().lower()
    session_samesite_ready = session_samesite in SAFE_SAMESITE_VALUES
    checks.append(
        SessionSecurityCheck(
            code="session_cookie_samesite",
            ready=session_samesite_ready,
            message=(
                "Session cookie uses a same-site policy."
                if session_samesite_ready
                else "Use Lax or Strict SameSite for the session cookie."
            ),
        )
    )

    csrf_samesite = str(
        getattr(settings_obj, "CSRF_COOKIE_SAMESITE", "Lax") or ""
    ).strip().lower()
    csrf_samesite_ready = csrf_samesite in SAFE_SAMESITE_VALUES
    checks.append(
        SessionSecurityCheck(
            code="csrf_cookie_samesite",
            ready=csrf_samesite_ready,
            message=(
                "CSRF cookie uses a same-site policy."
                if csrf_samesite_ready
                else "Use Lax or Strict SameSite for the CSRF cookie."
            ),
        )
    )

    return tuple(checks)
