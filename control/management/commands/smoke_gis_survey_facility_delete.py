"""Rollback-only production smoke for independent facility deletion."""
from __future__ import annotations

from uuid import uuid4

from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction
from django.urls import resolve, Resolver404

from control.models import GroupDBConfig
from control.management.commands.smoke_gis_survey_source_upload import _tenant_alias
from geoflow_ops.gis.changeset import apply_project_changeset, project_current_revision
from geoflow_ops.gis import central_definitions
from geoflow_ops.gis.layer_plan import project_layer_plan
from geoflow_ops.gis.qgis_sync import _quote_ident


class Command(BaseCommand):
    help = "Verify independent facility delete policy in production and roll back every DB write"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        if not options["apply"]:
            raise CommandError("Explicit --apply required")
        configs = (GroupDBConfig.objects.using("default").select_related("group")
                   .filter(group__status="active").exclude(db_alias="default").order_by("group_id"))
        for suffix in ('survey-links/','survey-link-changesets/','qfield/survey-links/',
                       'qfield/survey-link-changesets/','survey-reapply/','survey-reapply-preview/'):
            try:
                resolve('/gis/projects/11111111-1111-4111-8111-111111111401/api/'+suffix)
            except Resolver404:
                continue
            raise CommandError('retired_target_route_still_resolves')
        results = None
        chosen = None
        for config in configs:
            with _tenant_alias(config) as alias:
                with connections[alias].cursor() as cur:
                    cur.execute("SELECT id::text FROM prj.projects ORDER BY id")
                    project_ids = [row[0] for row in cur.fetchall()]
                fixture = None
                for project_id in project_ids:
                    plan = project_layer_plan(alias, project_id)
                    if not plan.get("ready") or not plan.get("gis_enabled"):
                        continue
                    template = None
                    depth = None
                    with connections[alias].cursor() as cur:
                        for layer in plan.get("layers") or []:
                            standard = str(layer.get("standard_name") or "").upper()
                            if standard != "WTL_PIPE_PS":
                                continue
                            table = _quote_ident(str(layer.get("physical_name") or ""))
                            cur.execute(
                                "SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='gis' AND table_name=%s AND column_name='saa_cde')",
                                [table.strip('"')],
                            )
                            if not cur.fetchone()[0]:
                                continue
                            template = (str(layer["id"]), table.strip('"'), standard, None)
                            depth = template
                    if template is not None and depth is not None:
                        fixture = (project_id, plan, template, depth)
                        break
                if fixture is None:
                    data = central_definitions.central_snapshot() or {}
                    central_layer = next(
                        (row for row in data.get("layers", [])
                         if str(row.get("standard_name") or "").upper() == "WTL_PIPE_PS"
                         and row.get("active")),
                        None,
                    )
                    for project_id in project_ids:
                        base_plan = project_layer_plan(alias, project_id)
                        if central_layer is None or not base_plan.get("ready"):
                            continue
                        table = str(central_layer.get("physical_name") or "")
                        with connections[alias].cursor() as cur:
                            cur.execute("SELECT to_regclass(%s) IS NOT NULL", [f"gis.{table}"])
                            if not cur.fetchone()[0]:
                                continue
                        layer = {
                            "id": central_layer["id"],
                            "standard_name": central_layer["standard_name"],
                            "physical_name": table,
                            "label": central_layer["label"],
                            "domain": central_layer["domain_code"],
                            "geometry_kind": central_layer["geometry_kind"],
                            "required": False,
                            "sort_order": central_layer["sort_order"],
                        }
                        config = {"group_id": None, "additions": {}, "private_items": {}, "overrides": {}}
                        smoke_plan = dict(base_plan)
                        smoke_plan["layers"] = [layer]
                        smoke_plan["form_definition"] = central_definitions.resolve(data, config, [layer])
                        target = (str(layer["id"]), table, "WTL_PIPE_PS", None)
                        fixture = (project_id, smoke_plan, target, target)
                        break
                if fixture is None:
                    continue
                project_id, plan, template, depth = fixture
                survey_id = str(uuid4())
                source_id = str(uuid4())
                source_group_id = str(uuid4())

                def prepare_survey(cur):
                    cur.execute(
                        """INSERT INTO gis.survey_source(
                             id,project_id,source_group_id,source_type,original_file_name,
                             version,is_active,note
                           ) VALUES (%s,%s,%s,'OTHER','facility-delete-smoke',1,true,'rollback-only')""",
                        [source_id, project_id, source_group_id],
                    )
                    cur.execute(
                        """INSERT INTO gis.survey(
                             id,project_id,source_id,source_row_id,name,code,raw_data,geom
                           ) VALUES (%s,%s,%s,'facility-delete-smoke','facility-delete-smoke',
                                     'SMOKE','{}'::jsonb,ST_SetSRID(ST_MakePoint(127,36),4326))""",
                        [survey_id, project_id, source_id],
                    )

                def clone_targets(cur, source, count):
                    layer_id, table, standard, source_id = source
                    cur.execute(
                        """SELECT column_name FROM information_schema.columns
                             WHERE table_schema='gis' AND table_name=%s
                               AND is_generated='NEVER' AND is_identity='NO'
                             ORDER BY ordinal_position""",
                        [table],
                    )
                    columns = [row[0] for row in cur.fetchall()]
                    if "id" not in columns or "project_id" not in columns:
                        raise CommandError("smoke template has no id/project_id")
                    quoted = ", ".join(_quote_ident(column) for column in columns)
                    created = []
                    for _ in range(count):
                        target_id = str(uuid4())
                        if source_id is None:
                            cur.execute(
                                f'''INSERT INTO "gis".{_quote_ident(table)} (id, project_id, geom)
                                    SELECT %s::uuid, %s::uuid, geom
                                      FROM gis.survey WHERE id=%s''',
                                [target_id, project_id, survey_id],
                            )
                            if cur.rowcount != 1:
                                raise CommandError("smoke Survey geometry insert failed")
                            created.append((layer_id, table, standard, target_id))
                            continue
                        expressions = []
                        params = []
                        for column in columns:
                            if column == "id":
                                expressions.append("%s::uuid")
                                params.append(target_id)
                            elif column == "project_id":
                                expressions.append("%s::uuid")
                                params.append(project_id)
                            else:
                                expressions.append(_quote_ident(column))
                        params.append(source_id)
                        cur.execute(
                            f'''INSERT INTO "gis".{_quote_ident(table)} ({quoted})
                                SELECT {", ".join(expressions)}
                                  FROM "gis".{_quote_ident(table)} WHERE id=%s''',
                            params,
                        )
                        if cur.rowcount != 1:
                            raise CommandError("smoke template clone failed")
                        created.append((layer_id, table, standard, target_id))
                    return created

                def run_case(name, source, count):
                    with transaction.atomic(using=alias):
                        with connections[alias].cursor() as cur:
                            prepare_survey(cur)
                            selected = clone_targets(cur, source, count)
                            if name == "depth_single":
                                cur.execute(
                                    "UPDATE gis.survey SET raw_code='SA900',code='SA900' WHERE id=%s",
                                    [survey_id],
                                )
                        base = project_current_revision(alias, project_id)
                        response = apply_project_changeset(
                            alias, project_id=project_id, plan=plan,
                            payload={"client_id": str(uuid4()), "changeset_id": str(uuid4()),
                                     "base_revision": base,
                                     "changes": [{"action": "delete", "layer": t[2], "id": t[3]} for t in selected]},
                        )
                        if response.get("deleted") != len(selected):
                            raise CommandError(f"{name}=delete_count_failed")
                        with connections[alias].cursor() as cur:
                            for layer_id, table, _standard, target_id in selected:
                                cur.execute(f'SELECT count(*) FROM "gis".{_quote_ident(table)} WHERE project_id=%s AND id=%s', [project_id, target_id])
                                if cur.fetchone()[0]:
                                    raise CommandError(f"{name}=feature_retained")
                            cur.execute("SELECT count(*) FROM gis.survey WHERE id=%s AND deleted_at IS NULL", [survey_id])
                            if cur.fetchone()[0] != 1:
                                raise CommandError(f"{name}=survey_changed")
                            if source_id:
                                cur.execute("SELECT count(*) FROM gis.survey_source WHERE id=%s AND deleted_at IS NULL", [source_id])
                                if cur.fetchone()[0] != 1:
                                    raise CommandError(f"{name}=source_changed")
                        with connections[alias].cursor() as cur:
                            cur.execute("SET CONSTRAINTS ALL IMMEDIATE")
                        transaction.set_rollback(True, using=alias)
                    return len(selected)

                results = {
                    "ordinary_single": run_case("ordinary_single", template, 1),
                    "survey_geometry_single": run_case("survey_geometry_single", template, 1),
                    "depth_single": run_case("depth_single", depth, 1),
                    "bulk_10": run_case("bulk_10", template, 10),
                    "bulk_20": run_case("bulk_20", template, 20),
                    "bulk_38": run_case("bulk_38", template, 38),
                }
                chosen = alias
                break
        if not results:
            raise CommandError("survey_facility_delete_smoke_fixture_unavailable")
        self.stdout.write(f"survey_facility_delete_smoke_tenant={chosen}")
        for key, value in results.items():
            self.stdout.write(f"survey_facility_delete_smoke_{key}={value}")
        self.stdout.write("survey_facility_delete_smoke_db_rollback=yes")
        self.stdout.write("RESULT gis_survey_facility_delete_smoke=SUCCESS")
