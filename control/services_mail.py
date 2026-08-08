# control/services_mail.py


def send_invite_email_with_set_password_link(user_id: str, email: str):
    """Disabled legacy invitation mail path retained only for stale callers.

    Phase 1 account creation and verification must use the explicit signup/outbox
    lifecycle. This helper previously created a raw legacy password-reset token
    and sent it immediately, which could bypass the current approval boundary if
    an old invitation view were accidentally re-exposed.
    """
    raise RuntimeError("Legacy invitation password email is disabled")
