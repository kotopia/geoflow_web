"""Apply the reviewed additive Survey lineage schema to active tenant databases."""
import importlib.util
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError



APP = "webgisapp"
MIGRATION = "0045_gis_survey_soft_delete"
DEPENDENCY = "0044_gis_survey_lineage"


def migration_sql():
    path = Path(__file__).resolve().parents[3] / "geoflow_ops" / "migrations" / f"{MIGRATION}.py"
    spec = importlib.util.spec_from_file_location("deploy_gis_survey_0045", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    operations = list(module.Migration.operations)
    if len(operations) != 1 or not isinstance(operations[0].sql, str):
        raise CommandError("Unexpected GIS Survey migration shape")
    return operations[0].sql


def survey_elevation_count(cursor):
    # survey_code is an optional legacy field, absent in current tenant stores.
    cursor.execute("""SELECT column_name FROM information_schema.columns
                       WHERE table_schema='gis' AND table_name='survey'
                         AND column_name IN ('survey_code','code','raw_code')""")
    available = {row[0] for row in cursor.fetchall()}
    columns = [name for name in ('survey_code','code','raw_code') if name in available]
    if not columns:
        raise RuntimeError('Survey code inventory columns missing')
    expression = ','.join('"'+name+'"' for name in columns)
    cursor.execute("SELECT count(*) FROM gis.survey WHERE upper(COALESCE("+expression+",''))='H'")
    return int(cursor.fetchone()[0])


def _validate(cursor, db_name):
    cursor.execute("""
        SELECT to_regclass('gis.survey_source'),to_regclass('gis.survey')
    """)
    if not all(cursor.fetchone()):
        raise RuntimeError(f"{db_name}: Survey lineage relations missing")
    expected = {
        "survey_source": {"deleted_at", "deleted_by", "delete_reason"},
        "survey": {"source_id", "source_row_id", "raw_crs", "raw_code", "raw_geoid_model",
                   "deleted_at", "deleted_by", "delete_reason"},
    }
    for table, required in expected.items():
        cursor.execute("""SELECT column_name FROM information_schema.columns
            WHERE table_schema='gis' AND table_name=%s""", [table])
        missing = required - {row[0] for row in cursor.fetchall()}
        if missing:
            raise RuntimeError(f"{db_name}: {table} missing {sorted(missing)}")


class Command(BaseCommand):
    help = "Install Survey Source and Point soft-delete prerequisites."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        from control.models import GroupDBConfig
        from control.services.gis_admin import tenant_cursor

        if not options["apply"]:
            raise CommandError("Explicit --apply required")
        sql = migration_sql()
        configs = list(GroupDBConfig.objects.using("default").filter(
            group__status="active").exclude(db_alias="default").order_by("group_id"))
        if not configs:
            raise CommandError("No active tenant databases")
        try:
            # Read-only prerequisite pass before the first schema mutation.
            for config in configs:
                with tenant_cursor(config.group_id, write=False) as cursor:
                    cursor.execute("SELECT to_regclass('django_migrations')")
                    if cursor.fetchone()[0] is None:
                        raise RuntimeError(f"{config.db_name}: migration history missing")
                    cursor.execute("SELECT EXISTS(SELECT 1 FROM django_migrations WHERE app=%s AND name=%s)",
                                   [APP, DEPENDENCY])
                    if not cursor.fetchone()[0]:
                        raise RuntimeError(f"{config.db_name}: missing dependency {DEPENDENCY}")
                    cursor.execute("SELECT count(*) FROM gis.survey_source")
                    source_count = int(cursor.fetchone()[0])
                    cursor.execute("SELECT count(*) FROM gis.survey")
                    point_count = int(cursor.fetchone()[0])
                    elevation_count = survey_elevation_count(cursor)
                    cursor.execute(
                        """SELECT conname,pg_get_constraintdef(oid)
                             FROM pg_constraint
                            WHERE conrelid IN ('gis.survey'::regclass,
                                               'gis.survey_source'::regclass)
                              AND contype='f'"""
                    )
                    fk_defs = [str(row[1]) for row in cursor.fetchall()]
                    if any("ON DELETE CASCADE" in value.upper() for value in fk_defs):
                        raise RuntimeError(f"{config.db_name}: unsafe Survey cascade FK")
                    self.stdout.write(
                        f"gis_survey_delete_inventory={config.db_name}:"
                        f"sources={source_count},points={point_count},"
                        f"h_points={elevation_count},"
                        f"fk_count={len(fk_defs)}"
                    )

            migrated = 0
            for config in configs:
                with tenant_cursor(config.group_id, write=True) as cursor:
                    cursor.execute("SET LOCAL lock_timeout='8s'")
                    cursor.execute("SET LOCAL statement_timeout='180s'")
                    cursor.execute("SELECT pg_advisory_xact_lock(hashtext('geoflow:gis:survey-lineage-0045'))")
                    cursor.execute("SELECT EXISTS(SELECT 1 FROM django_migrations WHERE app=%s AND name=%s)",
                                   [APP, MIGRATION])
                    already_applied = bool(cursor.fetchone()[0])
                    if not already_applied:
                        cursor.execute(sql)
                        cursor.execute("""INSERT INTO django_migrations(app,name,applied)
                            SELECT %s,%s,now() WHERE NOT EXISTS(
                              SELECT 1 FROM django_migrations WHERE app=%s AND name=%s)""",
                                       [APP, MIGRATION, APP, MIGRATION])
                    _validate(cursor, config.db_name)
                migrated += 0 if already_applied else 1
                self.stdout.write(f"gis_survey_lineage_tenant_ready={config.db_name}")
        except Exception as exc:
            raise CommandError("GIS Survey lineage deployment stopped (" + type(exc).__name__ + ").") from None
        self.stdout.write(f"gis_survey_lineage_migrated_count={migrated}")
        self.stdout.write(f"gis_survey_lineage_tenant_count={len(configs)}")
        self.stdout.write("gis_survey_lineage_deploy_complete=yes")
