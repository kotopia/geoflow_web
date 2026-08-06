from __future__ import annotations

from datetime import datetime
from typing import Callable
from urllib.parse import urlsplit

from django.conf import settings
from django.core.mail import send_mail


class SignupVerificationEmailDeliveryError(Exception):
    """Sanitized delivery failure; recipient and token must not be exposed."""


def send_signup_email_verification_email(
    *,
    to_email: str,
    verification_link: str,
    expires_at: datetime,
    mail_sender: Callable = send_mail,
    settings_obj=settings,
) -> None:
    recipient = str(to_email).strip()
    if not recipient:
        raise ValueError("recipient email is required")
    if not isinstance(expires_at, datetime):
        raise ValueError("verification expiry is required")

    parts = urlsplit(str(verification_link))
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError("verification link must be an absolute HTTP URL")

    subject = "[GeoFlow] 회원가입 이메일 인증 안내"
    body = (
        "안녕하세요.\n\n"
        "GeoFlow 회원가입 이메일 인증을 완료하려면 아래 링크를 이용해 주세요.\n"
        "이 링크는 제한된 시간 동안 한 번만 사용할 수 있습니다.\n\n"
        f"{verification_link}\n\n"
        "본인이 요청하지 않은 경우 이 메일을 무시하셔도 됩니다.\n"
    )
    sender = getattr(
        settings_obj,
        "DEFAULT_FROM_EMAIL",
        "no-reply@geoflow.local",
    )

    try:
        sent_count = mail_sender(
            subject,
            body,
            sender,
            [recipient],
            fail_silently=False,
        )
    except Exception:
        raise SignupVerificationEmailDeliveryError(
            "signup verification email delivery failed"
        ) from None
    if sent_count != 1:
        raise SignupVerificationEmailDeliveryError(
            "signup verification email delivery failed"
        )
