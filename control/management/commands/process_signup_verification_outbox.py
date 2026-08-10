from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from control.services.account_password_reset_delivery import (
    AccountPasswordResetConfigurationError,
    load_account_password_reset_delivery_config,
)
from control.services.account_password_reset_outbox_service import (
    process_next_account_password_reset_outbox_item,
)
from control.services.signup_verification_outbox_config import (
    load_signup_verification_outbox_config,
)
from control.services.signup_verification_outbox_runtime import (
    process_next_signup_verification_outbox_item,
)
from control.services.signup_verification_runtime import (
    load_signup_email_verification_key_ring,
)
from control.services.signup_verification_service import (
    EmailVerificationConfigurationError,
)


class Command(BaseCommand):
    help = (
        "Process a bounded batch of signup-verification and account-password-reset "
        "delivery outbox rows."
    )

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, required=True)

    def handle(self, *args, **options):
        limit = options["limit"]
        if limit <= 0:
            raise CommandError("--limit must be positive")

        try:
            signup_config = load_signup_verification_outbox_config()
            key_ring = load_signup_email_verification_key_ring()
        except EmailVerificationConfigurationError as exc:
            raise CommandError(str(exc)) from None

        try:
            reset_config = load_account_password_reset_delivery_config()
        except AccountPasswordResetConfigurationError:
            # Password-reset configuration must never disable the already-live
            # signup verification queue. The forgot-password endpoint will fail
            # closed until the reset configuration is valid.
            reset_config = None

        processed = 0
        outcomes: dict[str, int] = {}
        queue_index = 0
        consecutive_empty = 0
        queues_available = 2 if reset_config is not None else 1

        while processed < limit and consecutive_empty < queues_available:
            if reset_config is not None and queue_index % 2 == 1:
                queue_name = "password_reset"
                result = process_next_account_password_reset_outbox_item(
                    reset_url=reset_config.reset_url,
                    ttl=reset_config.token_ttl,
                    lease_for=reset_config.lease_for,
                    retry_delay=reset_config.retry_delay,
                    email_timeout=reset_config.email_timeout,
                    max_attempts=reset_config.max_attempts,
                    key_ring=key_ring,
                    settings_obj=settings,
                )
            else:
                queue_name = "signup_verification"
                result = process_next_signup_verification_outbox_item(
                    verification_url=signup_config.verification_url,
                    ttl=signup_config.token_ttl,
                    lease_for=signup_config.lease_for,
                    retry_delay=signup_config.retry_delay,
                    email_timeout=signup_config.email_timeout,
                    max_attempts=signup_config.max_attempts,
                    key_ring=key_ring,
                    settings_obj=settings,
                )

            queue_index += 1
            if not result.claimed:
                consecutive_empty += 1
                continue

            consecutive_empty = 0
            processed += 1
            outcome = result.outcome or "unknown"
            key = f"{queue_name}.{outcome}"
            outcomes[key] = outcomes.get(key, 0) + 1

        summary = ", ".join(
            f"{name}={count}" for name, count in sorted(outcomes.items())
        )
        reset_state = "enabled" if reset_config is not None else "disabled"
        self.stdout.write(
            f"mail outbox processed={processed} password_reset={reset_state}"
            + (f" ({summary})" if summary else "")
        )
