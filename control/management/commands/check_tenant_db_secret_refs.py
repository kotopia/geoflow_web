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
        "that every configured credential is an AWS Secrets Manager reference. "
        "Inactive tenant configs may keep an empty password, but active tenant "
        "configs may not. Secret values are never resolved or printed."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--strict",
            action="store_true",
            help=(
                "Fail when an active tenant credential is empty, any configured "
                "credential is plaintext, or any secret reference is malformed."
            ),
        )

    def handle(self, *args, **options):
        central_alias = getattr(settings, "CENTRAL_DB_ALIAS", "default")
        total = 0
        referenced = 0
        legacy = 0
        invalid = 0
        active_empty = 0
        inactive_empty = 0

        rows = (
            GroupDBConfig.objects.using(central_alias)
            .select_related("group")
            .order_by("db_alias")
        )
        for row in rows:
            total += 1
            stored_value = str(row.db_password or "").strip()
            group_status = str(getattr(row.group, "status", "") or "").strip().lower()

            if not stored_value:
                if group_status == "active":
                    active_empty += 1
                else:
                    inactive_empty += 1
                continue

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
        self.stdout.write(f"tenant_db_secret_ref_active_empty={active_empty}")
        self.stdout.write(f"tenant_db_secret_ref_inactive_empty={inactive_empty}")

        ready = legacy == 0 and invalid == 0 and active_empty == 0
        self.stdout.write(f"tenant_db_secret_refs_ready={'yes' if ready else 'no'}")
        if options["strict"] and not ready:
            raise CommandError("tenant database secret-reference audit failed")
