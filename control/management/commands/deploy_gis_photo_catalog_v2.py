"""Apply the reviewed central catalogue reset and tenant photo-column extension."""
import importlib.util
from pathlib import Path
from uuid import uuid4

from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction

from control.models import GroupDBConfig
from control.services.gis_admin import tenant_cursor


APP = "webgisapp"
MIGRATION = "0043_gis_feature_photo_catalog_v2"
DEPENDENCY = "0042_gis_feature_photo_image_metadata"


def migration_sql():
    path = Path(__file__).resolve().parents[3] / "geoflow_ops/migrations/0043_gis_feature_photo_catalog_v2.py"
    spec = importlib.util.spec_from_file_location("deploy_gis_photo_0043", path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module.Migration.operations[0].sql


def _insert_returning(cursor, table, columns, values, conflict="code"):
    row_id = str(uuid4())
    placeholders = ",".join(["%s"] * (len(values) + 1))
    cursor.execute(f"""INSERT INTO gis.{table}(id,{','.join(columns)})
        VALUES({placeholders}) ON CONFLICT({conflict}) DO UPDATE SET updated_at=now()
        RETURNING id::text""", [row_id, *values])
    return cursor.fetchone()[0]


def seed_catalogue(cursor):
    templates = {}
    for code, name, order in (("EXPOSED_PIPE", "노출관로측량", 0),
                              ("FACILITY", "시설물사진", 1), ("OTHER", "기타사진", 2)):
        templates[code] = _insert_returning(cursor, "photo_template",
            ["code","name","sort_order"], [code,name,order])
    variants = {}
    for key, template, code, name, order in (
        ("DIRECT","EXPOSED_PIPE","DIRECT","직접",0),
        ("INDIRECT","EXPOSED_PIPE","INDIRECT","간접",1),
        ("FACILITY","FACILITY","DEFAULT","기본",0),
        ("OTHER","OTHER","DEFAULT","기본",0),
    ):
        cursor.execute("""INSERT INTO gis.photo_variant(id,template_id,code,name,sort_order)
            VALUES(%s,%s,%s,%s,%s) ON CONFLICT(template_id,code) DO UPDATE SET
            name=EXCLUDED.name,sort_order=EXCLUDED.sort_order,active=true,updated_at=now()
            RETURNING id::text""", [str(uuid4()),templates[template],code,name,order])
        variants[key] = cursor.fetchone()[0]
    slots = (("DIRECT","BURIED","매설",0),("DIRECT","PAVED","포장",1),
             ("INDIRECT","BURIED","매설",0),("INDIRECT","NEAR","근접",1),
             ("INDIRECT","OFFSET","이격",2),("INDIRECT","PAVED","포장",3),
             ("FACILITY","FACILITY","시설물사진",0),("OTHER","OTHER","기타사진",0))
    for variant, code, name, order in slots:
        cursor.execute("""INSERT INTO gis.photo_slot(id,variant_id,code,name,min_count,max_count,sort_order)
            VALUES(%s,%s,%s,%s,1,1,%s) ON CONFLICT(variant_id,code) DO UPDATE SET
            name=EXCLUDED.name,sort_order=EXCLUDED.sort_order,active=true,updated_at=now()""",
            [str(uuid4()),variants[variant],code,name,order])
    cursor.execute("SELECT id::text FROM catalog.category_node WHERE level=2 AND active AND name=%s ORDER BY id LIMIT 1", ["상수"])
    l2 = cursor.fetchone()
    if not l2:
        raise RuntimeError("water L2 catalogue target missing")
    cursor.execute("""SELECT o.id::text FROM catalog.category_option_set s
        JOIN catalog.category_facet_option o ON o.facet_id=s.facet_id AND o.active
        WHERE s.level_no=3 AND s.l2_id=%s AND o.name=%s ORDER BY o.id LIMIT 1""",
        [l2[0], "노출관로 측량"])
    l3 = cursor.fetchone()
    if not l3:
        raise RuntimeError("exposed-pipe L3 catalogue target missing")
    assignments = (("WTL_PIPE_PS",("EXPOSED_PIPE","OTHER")),
                   ("WTL_MANH_PS",("FACILITY",)), ("WTL_ETC_PS",("OTHER",)))
    applied = 0
    for standard_name, template_codes in assignments:
        cursor.execute("""SELECT l.id::text FROM gis.definition_layer_catalog lc
            JOIN gis.definition_layer l ON l.id=lc.layer_id AND l.active
            WHERE lc.catalog_level=2 AND lc.catalog_item_id=%s AND l.standard_name=%s""",
            [l2[0],standard_name])
        layer = cursor.fetchone()
        if not layer:
            continue
        policy_id = str(uuid4())
        cursor.execute("""INSERT INTO gis.photo_policy(id,lv2_id,lv3_id,layer_id,sort_order)
            VALUES(%s,%s,%s,%s,0) RETURNING id::text""", [policy_id,l2[0],l3[0],layer[0]])
        policy_id = cursor.fetchone()[0]
        for order, template_code in enumerate(template_codes):
            cursor.execute("""INSERT INTO gis.photo_policy_template(id,policy_id,template_id,sort_order)
                VALUES(%s,%s,%s,%s)""", [str(uuid4()),policy_id,templates[template_code],order])
        applied += 1
    return applied


class Command(BaseCommand):
    help = "Reset pre-service central photo definitions and install catalogue v2 columns."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        if not options["apply"]:
            raise CommandError("Explicit --apply required")
        root = Path(__file__).resolve().parents[3]
        central_sql = (root / "docs/architecture/gis-photo-policy-central-v2.sql").read_text(encoding="utf-8")
        try:
            with transaction.atomic(using="default"), connections["default"].cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout='8s'")
                cursor.execute("SET LOCAL statement_timeout='120s'")
                cursor.execute("SELECT pg_advisory_xact_lock(hashtext('geoflow:gis:photo-catalog-v2'))")
                cursor.execute("""SELECT
                    (SELECT count(*) FROM gis.photo_template),
                    (SELECT count(*) FROM gis.photo_slot),
                    (SELECT count(*) FROM gis.photo_policy)""")
                before = cursor.fetchone()
                self.stdout.write(f"gis_photo_catalog_v2_central_reset_rows=templates:{before[0]},slots:{before[1]},policies:{before[2]}")
                cursor.execute(central_sql)
                seeded = seed_catalogue(cursor)
                cursor.execute("""SELECT to_regclass('gis.photo_variant'),
                    to_regclass('gis.photo_policy_template'),
                    EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='gis'
                      AND table_name='photo_slot' AND column_name='variant_id')""")
                if not all(cursor.fetchone()):
                    raise RuntimeError("central photo catalogue v2 validation failed")
                self.stdout.write(f"gis_photo_catalog_v2_seeded_layer_policies={seeded}")

            configs = list(GroupDBConfig.objects.using("default").filter(
                group__status="active").exclude(db_alias="default").order_by("group_id"))
            if not configs:
                raise RuntimeError("no active tenant databases")
            changed = 0
            for config in configs:
                with tenant_cursor(config.group_id, write=True) as cursor:
                    cursor.execute("SET LOCAL statement_timeout='120s'")
                    cursor.execute("SELECT pg_advisory_xact_lock(hashtext('geoflow:gis:photo-catalog-v2'))")
                    cursor.execute("SELECT EXISTS(SELECT 1 FROM django_migrations WHERE app=%s AND name=%s)", [APP, DEPENDENCY])
                    if not cursor.fetchone()[0]:
                        raise RuntimeError(f"{config.db_name}: missing dependency {DEPENDENCY}")
                    cursor.execute("SELECT count(*) FROM gis.feature_photo")
                    self.stdout.write(f"gis_photo_catalog_v2_tenant_existing_rows[{config.db_name}]={cursor.fetchone()[0]}")
                    cursor.execute(migration_sql())
                    cursor.execute("""INSERT INTO django_migrations(app,name,applied)
                        SELECT %s,%s,now() WHERE NOT EXISTS(
                          SELECT 1 FROM django_migrations WHERE app=%s AND name=%s)""",
                                   [APP,MIGRATION,APP,MIGRATION])
                    cursor.execute("""SELECT count(*)=3 FROM information_schema.columns
                        WHERE table_schema='gis' AND table_name='feature_photo'
                          AND column_name IN ('template_id','variant_id','title')""")
                    if not cursor.fetchone()[0]:
                        raise RuntimeError(f"{config.db_name}: tenant photo catalogue columns missing")
                changed += 1
            self.stdout.write("gis_photo_catalog_v2_s3_deleted=0")
            self.stdout.write(f"gis_photo_catalog_v2_tenant_count={changed}")
            self.stdout.write("gis_photo_catalog_v2_deploy_complete=yes")
        except Exception as exc:
            raise CommandError("GIS photo catalogue v2 deployment stopped (" + type(exc).__name__ + ").") from None
