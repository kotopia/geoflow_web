from django.core.management.base import BaseCommand, CommandError

from control.services.dependency_security_preflight import (
    inspect_django_security_baseline,
)
from control.services.production_runtime_preflight import (
    inspect_production_runtime_preflight,
)


class Command(BaseCommand):
    help = (
        "Run repository-side release readiness checks without DB, SMTP, S3, "
        "or other network access and without printing secret values."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Return a command error when any required release check fails.",
        )

    def handle(self, *args, **options):
        runtime = inspect_production_runtime_preflight()
        dependency = inspect_django_security_baseline()
        ready = runtime.ready and dependency.ready

        self.stdout.write(f"release_preflight_ready={'yes' if ready else 'no'}")
        for check in runtime.checks:
            self.stdout.write(f"[{check.status}] {check.code}: {check.message}")
        self.stdout.write(
            f"[{'PASS' if dependency.ready else 'FAIL'}] "
            f"{dependency.code}: {dependency.message}"
        )

        if options["strict"] and not ready:
            raise CommandError("release preflight failed")
