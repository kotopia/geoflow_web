"""Central-only additive rollout and read-only runtime verification."""

import importlib
import json

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connections, transaction
from django.db.migrations import RunSQL
from django.test import RequestFactory

from control.services import gis_references

MIGRATION = "0011_gis_reference_datasets"
PREREQUISITE = "0010_tenant_employee_registrations"
FOUNDATION = "0009_gis_reference_code_groups"
TABLES = (
    "reference_source",
    "reference_dataset",
    "reference_version",
    "reference_event",
)


def state(cur):
    cur.execute("SELECT to_regclass('django_migrations')")
    if not cur.fetchone()[0]:
        raise CommandError("reference_datasets_migration_history=missing")
    cur.execute(
        "SELECT name FROM django_migrations WHERE app='control' AND name IN (%s,%s,%s)",
        [FOUNDATION, PREREQUISITE, MIGRATION],
    )
    applied = {row[0] for row in cur.fetchall()}
    if FOUNDATION not in applied:
        raise CommandError("reference_datasets_foundation=missing_0009")
    cur.execute("SELECT to_regclass('public.tenant_employee_registrations')")
    if bool(cur.fetchone()[0]) != (PREREQUISITE in applied):
        raise CommandError("reference_datasets_prerequisite_schema_history=mismatch")
    if MIGRATION in applied and PREREQUISITE not in applied:
        raise CommandError("reference_datasets_prerequisite_history=inconsistent")
    # Inspect FK targets before stopping the service; never create accounts/roles.
    cur.execute(
        "SELECT to_regclass('public.users'),to_regclass('public.groups'),to_regclass('public.roles')"
    )
    if not all(cur.fetchone()):
        raise CommandError("reference_datasets_central_identity_tables=missing")
    cur.execute(
        "SELECT to_regclass(%s),to_regclass(%s),to_regclass(%s),to_regclass(%s)",
        ["gis." + table for table in TABLES],
    )
    found = cur.fetchone()
    if (any(found) and not all(found)) or bool(all(found)) != (MIGRATION in applied):
        raise CommandError(
            "reference_datasets_schema_history=mismatch_restore_required"
        )
    if all(found):
        # Exercise the actual columns consumed by the service, without row output.
        gis_references.snapshot(cur)
    return MIGRATION in applied


def apply_migration(cur, name):
    # Exact reviewed additive migrations only, not a general migrate/fake path.
    if name not in (PREREQUISITE, MIGRATION):
        raise CommandError("reference_datasets_migration=outside_contract")
    operations = importlib.import_module(
        "control.migrations." + name
    ).Migration.operations
    if (
        len(operations) != 1
        or not isinstance(operations[0], RunSQL)
        or not isinstance(operations[0].sql, str)
    ):
        raise CommandError("reference_datasets_migration=unexpected_operations")
    cur.execute(operations[0].sql)
    cur.execute(
        "INSERT INTO django_migrations(app,name,applied) VALUES ('control',%s,now())",
        [name],
    )


def apply_store(cur):
    cur.execute("SET LOCAL lock_timeout='8s'; SET LOCAL statement_timeout='180s'")
    cur.execute(
        "SELECT pg_advisory_xact_lock(hashtext('geoflow.central.gis.reference_datasets'))"
    )
    if not state(cur):
        cur.execute(
            "SELECT EXISTS(SELECT 1 FROM django_migrations WHERE app='control' AND name=%s)",
            [PREREQUISITE],
        )
        if not cur.fetchone()[0]:
            apply_migration(cur, PREREQUISITE)
        apply_migration(cur, MIGRATION)
    if not state(cur):
        raise CommandError("reference_datasets_apply=incomplete")


class Command(BaseCommand):
    help = "Apply central reference 0011 and its exact 0010 prerequisite; verify page/API read-only"

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--check", action="store_true")
        mode.add_argument("--apply", action="store_true")
        mode.add_argument("--verify", action="store_true")

    def handle(self, *args, **options):
        try:
            if options["apply"]:
                with (
                    transaction.atomic(using="default"),
                    connections["default"].cursor() as cur,
                ):
                    apply_store(cur)
                self.stdout.write("reference_datasets_apply=ready")
                return
            with connections["default"].cursor() as cur:
                applied = state(cur)
            if options["check"]:
                self.stdout.write(
                    "reference_datasets_pending=" + ("no" if applied else "yes")
                )
                return
            if not applied:
                raise CommandError("reference_datasets_runtime=schema_pending")
            self.verify()
        except DatabaseError:
            raise CommandError("reference_datasets_database=unavailable") from None

    def verify(self):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import AnonymousUser

        from control import views_gis_references as views

        with connections["default"].cursor() as cur:
            cur.execute(
                "SELECT email FROM users WHERE is_staff=true AND is_active=true ORDER BY id LIMIT 1"
            )
            row = cur.fetchone()
        if not row:
            raise CommandError("reference_datasets_smoke=active_staff_missing")
        # Unsaved identity bridge, no account creation, real central-admin guard.
        user = get_user_model()(username=row[0], email=row[0], is_staff=True)
        factory = RequestFactory()
        for view, path in (
            (views.dashboard, "/control/central/gis/references/"),
            (views.catalog_api, "/control/central/gis/references/api/"),
        ):
            request = factory.get(path)
            request.user, request.session = (
                user,
                {"scope": "central", "roles": [], "avatar_attachment_id": ""},
            )
            response = view(request)
            if response.status_code != 200:
                raise CommandError("reference_datasets_smoke=staff_get_failed")
            if view is views.dashboard:
                html = response.content.decode()
                if not all(
                    marker in html
                    for marker in (
                        'data-pane="datasets"',
                        'data-pane="sources"',
                        'data-pane="history"',
                    )
                ):
                    raise CommandError("reference_datasets_smoke=workspace_missing")
            elif not json.loads(response.content).get("ok"):
                raise CommandError("reference_datasets_smoke=api_failed")
            request.user = AnonymousUser()
            if view(request).status_code != 403:
                raise CommandError("reference_datasets_smoke=anonymous_not_denied")
        self.stdout.write("reference_datasets_staff_page_api=200")
        self.stdout.write("reference_datasets_anonymous_page_api=403")
        self.stdout.write("reference_datasets_runtime=SUCCESS")
