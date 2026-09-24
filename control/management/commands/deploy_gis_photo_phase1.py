"""Install the reviewed GIS photo Phase 1 schema in central and tenant stores."""
import importlib.util
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction

from control.models import GroupDBConfig
from control.services.gis_admin import tenant_cursor


APP = "webgisapp"
MIGRATION = "0039_gis_feature_photo"
DEPENDENCY = "0036_bid_interest_foundation"


def _sql(name):
    root = Path(__file__).resolve().parents[3]
    return (root / name).read_text(encoding="utf-8")


class Command(BaseCommand):
    help = "Install central photo policy definitions and tenant GIS photo storage."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        if not options["apply"]:
            raise CommandError("Explicit --apply required")

        central_sql = _sql("docs/architecture/gis-photo-policy-central.sql")
        migration_path = Path(__file__).resolve().parents[3] / "geoflow_ops/migrations/0039_gis_feature_photo.py"
        spec = importlib.util.spec_from_file_location("deploy_gis_photo_0039", migration_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        operations = module.Migration.operations
        if len(operations) != 1 or not isinstance(operations[0].sql, str):
            raise CommandError("Unexpected GIS photo migration shape")
        tenant_sql = operations[0].sql

        try:
            with transaction.atomic(using="default"), connections["default"].cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout='8s'")
                cursor.execute("SET LOCAL statement_timeout='120s'")
                cursor.execute("SELECT pg_advisory_xact_lock(hashtext('geoflow:gis:photo-phase1'))")
                cursor.execute("SELECT to_regclass('gis.definition_layer'), to_regclass('catalog.category_node')")
                if not all(cursor.fetchone()):
                    raise RuntimeError("central GIS definition or Catalog schema is missing")
                cursor.execute(central_sql)
                cursor.execute("SELECT to_regclass('gis.photo_policy'),to_regclass('gis.photo_template'),to_regclass('gis.photo_slot')")
                if not all(cursor.fetchone()):
                    raise RuntimeError("central GIS photo schema validation failed")

            configs = list(GroupDBConfig.objects.using("default").filter(
                group__status="active").exclude(db_alias="default").order_by("group_id"))
            if not configs:
                raise RuntimeError("no active tenant databases")
            migrated = 0
            for config in configs:
                with tenant_cursor(config.group_id, write=True) as cursor:
                    cursor.execute("SET LOCAL statement_timeout='120s'")
                    cursor.execute("SELECT pg_advisory_xact_lock(hashtext('geoflow:gis:photo-phase1'))")
                    cursor.execute("SELECT EXISTS(SELECT 1 FROM django_migrations WHERE app=%s AND name=%s)",
                                   [APP, DEPENDENCY])
                    if not cursor.fetchone()[0]:
                        raise RuntimeError(f"{config.db_name}: missing dependency {DEPENDENCY}")
                    cursor.execute(tenant_sql)
                    cursor.execute("""INSERT INTO django_migrations(app,name,applied)
                        SELECT %s,%s,now() WHERE NOT EXISTS(
                          SELECT 1 FROM django_migrations WHERE app=%s AND name=%s)""",
                                   [APP, MIGRATION, APP, MIGRATION])
                    cursor.execute("SELECT to_regclass('gis.feature_photo')")
                    if cursor.fetchone()[0] is None:
                        raise RuntimeError(f"{config.db_name}: feature_photo validation failed")
                migrated += 1

            self.stdout.write("gis_photo_central_schema=ready")
            self.stdout.write(f"gis_photo_tenant_count={migrated}")
            self.stdout.write("gis_photo_phase1_deploy_complete=yes")
        except Exception as exc:
            raise CommandError(
                "GIS photo Phase 1 deployment stopped (" + type(exc).__name__ + ")."
            ) from None
