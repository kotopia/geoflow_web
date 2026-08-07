from django.core.management.base import BaseCommand

from control.services.signup_verification_outbox_reconciliation import (
    summarize_signup_verification_outbox,
)


class Command(BaseCommand):
    help = "Report signup verification outbox invariant counts without PII."

    def handle(self, *args, **options):
        summary = summarize_signup_verification_outbox()
        self.stdout.write(
            " ".join(
                (
                    f"eligible_missing_outbox={summary.eligible_missing_outbox}",
                    f"active_outbox_ineligible={summary.active_outbox_ineligible}",
                    f"expired_processing_leases={summary.expired_processing_leases}",
                    f"duplicate_live_tokens={summary.duplicate_live_tokens}",
                )
            )
        )
