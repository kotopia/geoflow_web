"""Rollback-only production smoke for Survey-linked facility deletion."""
from __future__ import annotations

from uuid import uuid4

from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction

from control.models import GroupDBConfig
from control.management.commands.smoke_gis_survey_source_upload import _tenant_alias
from geoflow_ops.gis.changeset import apply_project_changeset, project_current_revision
from geoflow_ops.gis.layer_plan import project_layer_plan
from geoflow_ops.gis.qgis_sync import _quote_ident
from geoflow_ops.gis.survey_links import apply_survey_link_changeset


class Command(BaseCommand):
    help = "Verify linked facility delete policy in production and roll back every DB write"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        if not options["apply"]:
            raise CommandError("Explicit --apply required")
        configs = (GroupDBConfig.objects.using("default").select_related("group")
                   .filter(group__status="active").exclude(db_alias="default").order_by("group_id"))
        results = None
        chosen = None
        for config in configs:
            with _tenant_alias(config) as alias:
                with connections[alias].cursor() as cur:
                    cur.execute("SELECT id::text,project_id::text,source_id::text FROM gis.survey WHERE deleted_at IS NULL ORDER BY id LIMIT 1")
                    survey = cur.fetchone()
                if not survey:
                    continue
                survey_id, project_id, source_id = survey
                plan = project_layer_plan(alias, project_id)
                if not plan.get("ready") or not plan.get("gis_enabled"):
                    continue
                template = None
                depth = None
                with connections[alias].cursor() as cur:
                    for layer in plan.get("layers") or []:
                        standard = str(layer.get("standard_name") or "").upper()
                        if standard == "SURVEY":
                            continue
                        table = _quote_ident(str(layer.get("physical_name") or ""))
                        cur.execute(
                            f'''SELECT f.id::text FROM "gis".{table} f
                                 WHERE f.project_id=%s ORDER BY f.id LIMIT 1''',
                            [project_id],
                        )
                        row = cur.fetchone()
                        if row and template is None:
                            template = (str(layer["id"]), table.strip('"'), standard, row[0])
                        if standard == "WTL_PIPE_PS":
                            cur.execute(
                                "SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='gis' AND table_name=%s AND column_name='saa_cde')",
                                [table.strip('"')],
                            )
                            if cur.fetchone()[0]:
                                cur.execute(
                                    f'''SELECT f.id::text FROM "gis".{table} f
                                         WHERE f.project_id=%s AND f.saa_cde='SA900'
                                         ORDER BY f.id LIMIT 1''',
                                    [project_id],
                                )
                                row = cur.fetchone()
                                if row:
                                    depth = (str(layer["id"]), table.strip('"'), standard, row[0])
                if template is None or depth is None:
                    continue

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

                def run_case(name, source, count, linked_count):
                    with transaction.atomic(using=alias):
                        link_ids = []
                        with connections[alias].cursor() as cur:
                            selected = clone_targets(cur, source, count)
                            for layer_id, _table, _standard, target_id in selected[:linked_count]:
                                link_id = str(uuid4())
                                cur.execute(
                                    """INSERT INTO gis.survey_link(id,survey_id,layer_id,target_id,match_method,link_role,link_status)
                                       VALUES (%s,%s,%s,%s,'manual','POINT','LINKED')""",
                                    [link_id, survey_id, layer_id, target_id],
                                )
                                link_ids.append(link_id)
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
                            if link_ids:
                                cur.execute("SELECT count(*) FROM gis.survey_link WHERE id=ANY(%s::uuid[]) AND link_status='UNLINKED'", [link_ids])
                                if cur.fetchone()[0] != len(link_ids):
                                    raise CommandError(f"{name}=provenance_not_detached")
                            cur.execute("SELECT count(*) FROM gis.survey WHERE id=%s AND deleted_at IS NULL", [survey_id])
                            if cur.fetchone()[0] != 1:
                                raise CommandError(f"{name}=survey_changed")
                            if source_id:
                                cur.execute("SELECT count(*) FROM gis.survey_source WHERE id=%s AND deleted_at IS NULL", [source_id])
                                if cur.fetchone()[0] != 1:
                                    raise CommandError(f"{name}=source_changed")
                        transaction.set_rollback(True, using=alias)
                    return len(selected)

                results = {
                    "unlinked_single": run_case("unlinked_single", template, 1, 0),
                    "linked_single": run_case("linked_single", template, 1, 1),
                    "depth_single": run_case("depth_single", depth, 1, 1),
                    "linked_10": run_case("linked_10", template, 10, 10),
                    "mixed_20": run_case("mixed_20", template, 20, 10),
                    "linked_38": run_case("linked_38", template, 38, 38),
                }

                with transaction.atomic(using=alias):
                    with connections[alias].cursor() as cur:
                        old_target, new_target = clone_targets(cur, template, 2)
                        old_link = str(uuid4())
                        cur.execute(
                            "INSERT INTO gis.survey_link(id,survey_id,layer_id,target_id,match_method,link_role,link_status) VALUES (%s,%s,%s,%s,'manual','POINT','LINKED')",
                            [old_link, survey_id, old_target[0], old_target[3]],
                        )
                    deleted = apply_project_changeset(
                        alias, project_id=project_id, plan=plan,
                        payload={"client_id": str(uuid4()), "changeset_id": str(uuid4()),
                                 "base_revision": project_current_revision(alias, project_id),
                                 "changes": [{"action": "delete", "layer": old_target[2], "id": old_target[3]}]},
                    )
                    apply_survey_link_changeset(
                        alias, project_id=project_id, plan=plan,
                        payload={"client_id": str(uuid4()), "changeset_id": str(uuid4()),
                                 "base_revision": deleted["current_revision"],
                                 "changes": [{"action": "create", "id": str(uuid4()),
                                              "survey_id": survey_id, "layer": new_target[2],
                                              "target_id": new_target[3], "match_method": "manual"}]},
                    )
                    transaction.set_rollback(True, using=alias)
                results["recreate"] = 1
                chosen = alias
                break
        if not results:
            raise CommandError("survey_facility_delete_smoke_fixture_unavailable")
        self.stdout.write(f"survey_facility_delete_smoke_tenant={chosen}")
        for key, value in results.items():
            self.stdout.write(f"survey_facility_delete_smoke_{key}={value}")
        self.stdout.write("survey_facility_delete_smoke_db_rollback=yes")
        self.stdout.write("RESULT gis_survey_facility_delete_smoke=SUCCESS")
