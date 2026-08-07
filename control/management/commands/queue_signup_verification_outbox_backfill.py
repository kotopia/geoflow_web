from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from control.services.signup_verification_outbox_reconciliation import (
    queue_missing_signup_verification_outbox_batch,
)


class Command(BaseCommand):
    help = "Queue a bounded, explicitly scoped signup verification outbox backfill."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, required=True)
        parser.add_argument("--submitted-after", required=True)
        parser.add_argument("--execute", action="store_true")

    def handle(self, *args, **options):
        if not options["execute"]:
            raise CommandError("--execute is required for backfill writes")

        limit = options["limit"]
        if limit <= 0:
            raise CommandError("--limit must be positive")

        submitted_after = parse_datetime(options["submitted_after"])
        if submitted_after is None or not timezone.is_aware(submitted_after):
            raise CommandError(
                "--submitted-after must be an ISO-8601 timezone-aware datetime"
            )

        result = queue_missing_signup_verification_outbox_batch(
            submitted_after=submitted_after,
            limit=limit,
        )
        self.stdout.write(
            f"signup verification outbox backfill selected={result.selected} "
            f"enqueued={result.enqueued}"
        )
