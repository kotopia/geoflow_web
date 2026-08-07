from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

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
    help = "Process a bounded batch of signup verification delivery outbox rows."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, required=True)

    def handle(self, *args, **options):
        limit = options["limit"]
        if limit <= 0:
            raise CommandError("--limit must be positive")

        try:
            config = load_signup_verification_outbox_config()
            key_ring = load_signup_email_verification_key_ring()
        except EmailVerificationConfigurationError as exc:
            raise CommandError(str(exc)) from None

        processed = 0
        outcomes: dict[str, int] = {}
        while processed < limit:
            result = process_next_signup_verification_outbox_item(
                verification_url=config.verification_url,
                ttl=config.token_ttl,
                lease_for=config.lease_for,
                retry_delay=config.retry_delay,
                email_timeout=config.email_timeout,
                max_attempts=config.max_attempts,
                key_ring=key_ring,
                settings_obj=settings,
            )
            if not result.claimed:
                break
            processed += 1
            outcome = result.outcome or "unknown"
            outcomes[outcome] = outcomes.get(outcome, 0) + 1

        summary = ", ".join(
            f"{name}={count}" for name, count in sorted(outcomes.items())
        )
        self.stdout.write(
            f"signup verification outbox processed={processed}"
            + (f" ({summary})" if summary else "")
        )
