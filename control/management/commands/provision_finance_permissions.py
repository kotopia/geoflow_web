"""Register Finance permissions and explicitly selected existing role mappings.

Inspection is the default. This command never changes roles, users, tenant
schemas or existing mappings. Production --apply requires operational approval.
"""
from __future__ import annotations

from uuid import uuid4

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from control.models import Permission, Role, RolePermission


FINANCE_PERMISSION_CODES = ("finance.view", "finance.edit")


def requested_role_permissions(read_roles, edit_roles) -> dict[str, set[str]]:
    readers = {str(code).strip() for code in read_roles if str(code).strip()}
    editors = {str(code).strip() for code in edit_roles if str(code).strip()}
    return {"finance.view": readers | editors, "finance.edit": editors}


class Command(BaseCommand):
    help = "Inspect Finance permission registration; use --apply only after approving the displayed role plan."

    def add_arguments(self, parser):
        parser.add_argument("--read-role", action="append", default=[])
        parser.add_argument("--edit-role", action="append", default=[])
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        alias = getattr(settings, "GF_AUTHZ_CENTRAL_ALIAS", "default")
        if alias != getattr(settings, "CENTRAL_DB_ALIAS", "default"):
            raise CommandError("Central authorization alias does not match the central database.")
        requested = requested_role_permissions(options["read_role"], options["edit_role"])
        role_codes = set().union(*requested.values())
        # A read-only plan performs SELECTs only, including no get_or_create.
        roles = {role.code: role for role in Role.objects.using(alias).filter(code__in=role_codes)}
        missing = role_codes - roles.keys()
        if missing:
            raise CommandError("Unknown role codes: " + ", ".join(sorted(missing)))
        permissions = {
            permission.code: permission
            for permission in Permission.objects.using(alias).filter(code__in=FINANCE_PERMISSION_CODES)
        }
        for code in FINANCE_PERMISSION_CODES:
            permission = permissions.get(code)
            existing_roles = (
                set(RolePermission.objects.using(alias).filter(permission=permission).values_list("role__code", flat=True))
                if permission else set()
            )
            self.stdout.write(
                f"{code}: {'exists' if permission else 'missing'}; "
                f"existing_roles={','.join(sorted(existing_roles)) or '-'}; "
                f"add_roles={','.join(sorted(requested[code] - existing_roles)) or '-'}"
            )
        if not options["apply"]:
            self.stdout.write("Read-only plan; no changes made. Role mappings apply to every tenant using that role.")
            return
        with transaction.atomic(using=alias):
            for code in FINANCE_PERMISSION_CODES:
                permission, _created = Permission.objects.using(alias).get_or_create(
                    code=code, defaults={"id": uuid4()}
                )
                for role_code in sorted(requested[code]):
                    RolePermission.objects.using(alias).get_or_create(
                        role=roles[role_code], permission=permission
                    )
        self.stdout.write("Finance permissions applied. No existing grants or user assignments were removed.")
