from django.core.management.base import BaseCommand, CommandError

from control.services.account_password_reset_schema_readiness import (
    inspect_account_password_reset_schema_readiness,
)


class Command(BaseCommand):
    help = "Read-only central schema audit for the account password-reset boundary."

    def add_arguments(self, parser):
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Return a command error when the required schema is not ready.",
        )

    def handle(self, *args, **options):
        result = inspect_account_password_reset_schema_readiness()
        self.stdout.write(
            f"account_password_reset_schema_ready={'yes' if result.ready else 'no'}"
        )
        for issue in result.issues:
            self.stdout.write(f"issue={issue}")

        if options["strict"] and not result.ready:
            raise CommandError("account password reset schema is not ready")
