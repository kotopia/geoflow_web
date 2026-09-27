"""Apply additive GIS photo image metadata storage to active tenant databases."""
import importlib.util
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from control.models import GroupDBConfig
from control.services.gis_admin import tenant_cursor


APP = "webgisapp"
MIGRATION = "0042_gis_feature_photo_image_metadata"
DEPENDENCY = "0041_gis_feature_photo_edited_representation"


class Command(BaseCommand):
    help = "Install additive image_metadata storage for normalized GIS photos."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        if not options["apply"]:
            raise CommandError("Explicit --apply required")
        path = (Path(__file__).resolve().parents[3] / "geoflow_ops/migrations" / f"{MIGRATION}.py")
        spec = importlib.util.spec_from_file_location("deploy_gis_photo_0042", path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        operations = module.Migration.operations
        if len(operations) != 1 or not isinstance(operations[0].sql, str):
            raise CommandError("Unexpected GIS photo Phase 4 migration shape")
        configs = list(GroupDBConfig.objects.using("default").filter(
            group__status="active").exclude(db_alias="default").order_by("group_id"))
        if not configs:
            raise CommandError("No active tenant databases")
        migrated = 0
        try:
            for config in configs:
                with tenant_cursor(config.group_id, write=True) as cursor:
                    cursor.execute("SET LOCAL statement_timeout='120s'")
                    cursor.execute("SELECT pg_advisory_xact_lock(hashtext('geoflow:gis:photo-phase4'))")
                    cursor.execute("SELECT EXISTS(SELECT 1 FROM django_migrations WHERE app=%s AND name=%s)", [APP,DEPENDENCY])
                    if not cursor.fetchone()[0]:
                        raise RuntimeError(f"{config.db_name}: missing dependency {DEPENDENCY}")
                    cursor.execute(operations[0].sql)
                    cursor.execute("""INSERT INTO django_migrations(app,name,applied)
                        SELECT %s,%s,now() WHERE NOT EXISTS(
                          SELECT 1 FROM django_migrations WHERE app=%s AND name=%s)""", [APP,MIGRATION,APP,MIGRATION])
                    cursor.execute("""SELECT count(*) FROM information_schema.columns
                        WHERE table_schema='gis' AND table_name='feature_photo'
                          AND column_name='image_metadata'""")
                    if int(cursor.fetchone()[0]) != 1:
                        raise RuntimeError(f"{config.db_name}: image_metadata validation failed")
                migrated += 1
        except Exception as exc:
            raise CommandError("GIS photo Phase 4 deployment stopped (" + type(exc).__name__ + ").") from None
        self.stdout.write(f"gis_photo_phase4_tenant_count={migrated}")
        self.stdout.write("gis_photo_phase4_deploy_complete=yes")
