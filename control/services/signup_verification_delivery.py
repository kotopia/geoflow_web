from __future__ import annotations

from urllib.parse import urlencode, urlsplit, urlunsplit


def build_signup_email_verification_link(
    verification_url: str,
    token: str,
) -> str:
    """Place the raw token only in the URL fragment, never path or query."""

    if not isinstance(verification_url, str) or not verification_url:
        raise ValueError("verification URL is required")
    if not isinstance(token, str) or not token:
        raise ValueError("verification token is required")

    parts = urlsplit(verification_url)
    if parts.fragment:
        raise ValueError("verification URL must not contain a fragment")

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
