from django.core.management.base import BaseCommand, CommandError

from control.services.dependency_security_preflight import (
    inspect_django_security_baseline,
)
from control.services.object_storage_runtime_preflight import (
    inspect_object_storage_runtime,
)
from control.services.production_runtime_preflight import (
    inspect_production_runtime_preflight,
)
from control.services.route_security_preflight import (
    inspect_route_security_boundaries,
)
from control.services.session_security_preflight import (
    inspect_session_security_baseline,
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
        session_checks = inspect_session_security_baseline()
        storage_checks = inspect_object_storage_runtime()
        route_checks = inspect_route_security_boundaries()
        session_ready = all(check.ready for check in session_checks)
        storage_ready = all(check.ready for check in storage_checks)
        routes_ready = all(check.ready for check in route_checks)
        ready = (
            runtime.ready
            and dependency.ready
            and session_ready
            and storage_ready
            and routes_ready
        )

        self.stdout.write(f"release_preflight_ready={'yes' if ready else 'no'}")
        for check in runtime.checks:
            self.stdout.write(f"[{check.status}] {check.code}: {check.message}")
        self.stdout.write(
            f"[{'PASS' if dependency.ready else 'FAIL'}] "
            f"{dependency.code}: {dependency.message}"
        )
        for check in session_checks:
            self.stdout.write(
                f"[{'PASS' if check.ready else 'FAIL'}] "
                f"{check.code}: {check.message}"
            )
        for check in storage_checks:
            self.stdout.write(
                f"[{'PASS' if check.ready else 'FAIL'}] "
                f"{check.code}: {check.message}"
            )
        for check in route_checks:
            self.stdout.write(
                f"[{'PASS' if check.ready else 'FAIL'}] "
                f"{check.code}: {check.message}"
            )

        if options["strict"] and not ready:
            raise CommandError("release preflight failed")
