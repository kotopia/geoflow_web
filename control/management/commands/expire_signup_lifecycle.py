from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from control.services.signup_request_expiration_service import expire_signup_requests


UNVERIFIED_EXPIRY_DAYS = 7
PENDING_APPROVAL_EXPIRY_DAYS = 30


class Command(BaseCommand):
    help = (
        "Expire stale signup requests using the approved lifecycle policy. "
        "Without --execute, only print the cutoffs and perform no database work."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Apply expiration transitions. Omit for a no-DB policy preview.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=100,
            help="Maximum rows per status in one execution (1-500).",
        )

    def handle(self, *args, **options):
        batch_size = int(options["batch_size"])
        if not 1 <= batch_size <= 500:
            raise CommandError("--batch-size must be between 1 and 500")

        now = timezone.now()
        unverified_cutoff = now - timedelta(days=UNVERIFIED_EXPIRY_DAYS)
        approval_cutoff = now - timedelta(days=PENDING_APPROVAL_EXPIRY_DAYS)

        if not options["execute"]:
            self.stdout.write(
                "dry-run policy only; no database query/write performed: "
                f"pending_email_verification_days={UNVERIFIED_EXPIRY_DAYS} "
                f"pending_approval_days={PENDING_APPROVAL_EXPIRY_DAYS}"
            )
            return

        try:
            expired_unverified = expire_signup_requests(
                status="pending_email_verification",
                cutoff=unverified_cutoff,
                batch_size=batch_size,
            )
            expired_approval = expire_signup_requests(
                status="pending_approval",
                cutoff=approval_cutoff,
                batch_size=batch_size,
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                "signup lifecycle expiration complete: "
                f"pending_email_verification={expired_unverified} "
                f"pending_approval={expired_approval}"
            )
        )
