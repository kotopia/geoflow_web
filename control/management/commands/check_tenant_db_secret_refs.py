from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from control.models import GroupDBConfig
from control.services.tenant_db_secret_resolver import (
    TenantDBCredentialError,
    parse_tenant_db_secret_reference,
)


class Command(BaseCommand):
    help = (
        "Read tenant DB credential metadata from the central database and verify "
        "that configured passwords are AWS Secrets Manager references. Secret "
        "values are never resolved or printed."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Fail when any tenant credential is plaintext or malformed.",
        )

    def handle(self, *args, **options):
        central_alias = getattr(settings, "CENTRAL_DB_ALIAS", "default")
        total = 0
        referenced = 0
        legacy = 0
        invalid = 0

        for stored_value in (
            GroupDBConfig.objects.using(central_alias)
            .order_by("db_alias")
            .values_list("db_password", flat=True)
        ):
            total += 1
            try:
                reference = parse_tenant_db_secret_reference(stored_value)
            except TenantDBCredentialError:
                invalid += 1
                continue
            if reference is None:
                legacy += 1
            else:
                referenced += 1

        self.stdout.write(f"tenant_db_secret_ref_total={total}")
        self.stdout.write(f"tenant_db_secret_ref_ready={referenced}")
        self.stdout.write(f"tenant_db_secret_ref_legacy={legacy}")
        self.stdout.write(f"tenant_db_secret_ref_invalid={invalid}")

        ready = legacy == 0 and invalid == 0
        self.stdout.write(f"tenant_db_secret_refs_ready={'yes' if ready else 'no'}")
        if options["strict"] and not ready:
            raise CommandError("tenant database secret-reference audit failed")
