from django.core.management.base import BaseCommand, CommandError

from control.services.production_runtime_preflight import (
    inspect_production_runtime_preflight,
)


class Command(BaseCommand):
    help = (
        "Inspect production runtime configuration without DB, SMTP, S3, "
        "or other network access and without printing secret values."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Return a command error when any required production check fails.",
        )

    def handle(self, *args, **options):
        result = inspect_production_runtime_preflight()
        self.stdout.write(
            f"production_runtime_ready={'yes' if result.ready else 'no'}"
        )
        for check in result.checks:
            self.stdout.write(f"[{check.status}] {check.code}: {check.message}")

        if options["strict"] and not result.ready:
            raise CommandError("production runtime preflight failed")
