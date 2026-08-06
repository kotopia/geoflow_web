from __future__ import annotations

from urllib.parse import urlencode, urlsplit, urlunsplit

from django.views.decorators.debug import sensitive_variables


def validate_signup_email_verification_url(verification_url: str) -> None:
    """Fail before persistence when the configured verification URL is unusable."""

    if not isinstance(verification_url, str) or not verification_url:
        raise ValueError("verification URL is required")
    parts = urlsplit(verification_url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError("verification URL must be an absolute HTTP URL")
    if parts.fragment:
        raise ValueError("verification URL must not contain a fragment")


@sensitive_variables("token")
def build_signup_email_verification_link(
    verification_url: str,
    token: str,
) -> str:
    """Place the raw token only in the URL fragment, never path or query."""

    validate_signup_email_verification_url(verification_url)
    if not isinstance(token, str) or not token:
        raise ValueError("verification token is required")

    parts = urlsplit(verification_url)

    fragment = urlencode({"token": token})
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            parts.query,
            fragment,
        )
    )
