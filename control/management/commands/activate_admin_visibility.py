"""Apply only the separately approved central visibility migration."""
import hashlib
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction
from django.db.migrations.executor import MigrationExecutor


TARGET = ("control", "0007_admin_visibility")
REVIEWED_BLOB = "4dedb1abbd30304b6ffc3ebf997472763a3b5632"


class Command(BaseCommand):
    help = "Inspect central visibility activation; --apply requires operational approval."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        alias = getattr(settings, "CENTRAL_DB_ALIAS", "default")
        connection = connections[alias]
        if connection.vendor != "postgresql":
            raise CommandError("central_postgresql_required")
        source = (Path(__file__).resolve().parents[2] / "migrations/0007_admin_visibility.py").read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(source)).encode() + b"\0" + source).hexdigest()
        if blob != REVIEWED_BLOB:
            raise CommandError("unreviewed_admin_visibility_migration")

        with transaction.atomic(using=alias), connection.cursor() as cur:
            # Serialize retries; failure rolls back schema, backfill and recorder.
            cur.execute("SET LOCAL lock_timeout = '10s'")
            cur.execute("SET LOCAL statement_timeout = '120s'")
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ["geoflow-central-visibility-0007"])
            executor = MigrationExecutor(connection)
            executor.loader.check_consistent_history(connection)
            plan = executor.migration_plan([TARGET])
            if any((migration.app_label, migration.name) != TARGET or backwards for migration, backwards in plan):
                raise CommandError("unexpected_central_migration_plan")
            self.stdout.write(f"central_visibility_pending={len(plan)}")
            cur.execute("SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='groups' AND column_name='deleted_at')")
            self.stdout.write(f"central_groups_deleted_marker={str(cur.fetchone()[0]).lower()}")
            if not options["apply"]:
                return

            def finance_grants():
                cur.execute("SELECT rp.role_id::text, rp.permission_id::text FROM role_permissions rp JOIN permissions p ON p.id=rp.permission_id WHERE p.code IN ('finance.view','finance.edit') ORDER BY 1,2")
                return cur.fetchall()

            before = finance_grants()
            executor.migrate([TARGET], plan=plan)
            cur.execute("SELECT deleted_at FROM users LIMIT 0")
            cur.execute("SELECT group_id,bids,gis,finance,updated_at FROM group_service_menu_settings LIMIT 0")
            if finance_grants() != before:
                raise CommandError("finance_grants_changed_during_visibility_activation")
            if TARGET not in executor.recorder.applied_migrations():
                raise CommandError("central_visibility_migration_not_recorded")
        self.stdout.write("central_visibility_activated=yes")
        self.stdout.write("finance_grants_preserved=yes")
