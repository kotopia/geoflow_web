"""Register Finance permissions and explicitly selected existing role mappings.

Inspection is the default. This command never changes roles, users, tenant
schemas or existing mappings. Production --apply requires operational approval.
"""
from __future__ import annotations

from uuid import UUID, uuid4

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction

from control.models import Permission, Role, RolePermission


FINANCE_PERMISSION_CODES = ("finance.view", "finance.edit")
FINANCE_PERMISSION_LABELS = {"finance.view": "재무 조회", "finance.edit": "재무 편집"}


def _insert_registry_row(alias, model, lookup, optional_values=None):
    """Respect physical central columns that the unmanaged models may omit."""
    connection = connections[alias]
    quote = connection.ops.quote_name
    with connection.cursor() as cursor:
        fields = connection.introspection.get_table_description(cursor, model._meta.db_table)
        values = dict(lookup)
        for name, value in (optional_values or {}).items():
            if any(field.name == name for field in fields):
                values[name] = value
        unsupported = []
        for field in fields:
            if field.name in values or field.null_ok or field.default is not None:
                continue
            field_type = connection.introspection.get_field_type(field.type_code, field)
            if field_type in {"AutoField", "BigAutoField", "SmallAutoField"}:
                continue
            if field.name == "id" and field_type == "UUIDField":
                values["id"] = uuid4()
                continue
            unsupported.append(field.name)
        if unsupported:
            raise CommandError("Unsupported required registry columns: " + ", ".join(sorted(unsupported)))
        columns = list(values)
        cursor.execute(
            f"INSERT INTO {quote(model._meta.db_table)} "
            f"({', '.join(quote(name) for name in columns)}) "
            f"VALUES ({', '.join(['%s'] * len(columns))}) "
            f"ON CONFLICT ({', '.join(quote(name) for name in lookup)}) DO NOTHING",
            [
                value.hex if isinstance(value, UUID) and not connection.features.has_native_uuid_field else value
                for value in (values[name] for name in columns)
            ],
        )


def _register_permission(alias, code):
    existing = Permission.objects.using(alias).filter(code=code).first()
    if existing is not None:
        return existing
    _insert_registry_row(alias, Permission, {"code": code}, {
        "id": uuid4(), "name": FINANCE_PERMISSION_LABELS[code],
        "description": FINANCE_PERMISSION_LABELS[code],
    })
    return Permission.objects.using(alias).get(code=code)


def _register_role_permission(alias, role, permission):
    _insert_registry_row(alias, RolePermission, {"role_id": role.id, "permission_id": permission.id})


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
                permission = _register_permission(alias, code)
                for role_code in sorted(requested[code]):
                    _register_role_permission(alias, roles[role_code], permission)
        self.stdout.write("Finance permissions applied. No existing grants or user assignments were removed.")
