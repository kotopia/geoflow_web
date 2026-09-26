"""Read-only production proof for project photo-policy delivery into QGIS manifests."""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from control.models import GroupDBConfig
from control.services import gis_photo_policy
from control.services.gis_admin import tenant_cursor
from geoflow_ops.gis import central_definitions, layer_plan
from geoflow_ops.gis.gpkg import project_geopackage_layer_manifest


TARGETS = {"WTL_FLOW_PS", "WTL_PIPE_PS"}


class Command(BaseCommand):
    help = "Read-only diagnosis of central photo policy to QGIS layer UUID delivery."

    def handle(self, *args, **options):
        definition = central_definitions.central_snapshot()
        photo = gis_photo_policy.central_snapshot() if hasattr(gis_photo_policy, "central_snapshot") else None
        if definition is None:
            raise CommandError("central_definition_unavailable")
        if photo is None:
            from geoflow_ops.gis.photo_policy_views import central_photo_snapshot
            photo = central_photo_snapshot()
        if photo is None:
            raise CommandError("photo_policy_unavailable")

        central_layers = {
            str(row.get("standard_name") or "").upper(): row
            for row in definition.get("layers") or []
            if str(row.get("standard_name") or "").upper() in TARGETS
        }
        report = {
            "photo_policy_revision": photo.get("revision"),
            "central_layers": {
                name: {"id": str(row.get("id") or ""), "physical_name": row.get("physical_name")}
                for name, row in central_layers.items()
            },
            "projects": [],
        }

        configs = GroupDBConfig.objects.using("default").filter(group__status="active").exclude(db_alias="default")
        for config in configs:
            with tenant_cursor(config.group_id, write=False) as cur:
                cur.execute("SELECT DISTINCT project_id::text FROM prj.scope_item ORDER BY project_id::text")
                project_ids = [row[0] for row in cur.fetchall()]
            for project_id in project_ids:
                plan = layer_plan.project_layer_plan(config.db_alias, project_id)
                targets = [row for row in plan.get("layers") or []
                           if str(row.get("standard_name") or "").upper() in TARGETS]
                if not targets:
                    continue
                with tenant_cursor(config.group_id, write=False) as cur:
                    cur.execute("SELECT lv2_id::text,lv3_id::text FROM prj.scope_item WHERE project_id=%s", [project_id])
                    scopes = cur.fetchall()
                package = {str(row.get("standard_name") or "").upper(): row
                           for row in project_geopackage_layer_manifest(config.db_alias, plan)}
                item = {"tenant": config.db_alias, "project_id": project_id,
                        "scopes": scopes, "photo_policy_url": f"/gis/projects/{project_id}/api/photo-policies/",
                        "layers": []}
                for layer in targets:
                    standard = str(layer.get("standard_name") or "").upper()
                    policy = gis_photo_policy.resolve(photo, scopes, str(layer.get("id") or ""), {})
                    feature_id = None
                    with tenant_cursor(config.group_id, write=False) as cur:
                        cur.execute(f'SELECT id::text FROM gis."{layer["physical_name"]}" WHERE project_id=%s LIMIT 1', [project_id])
                        row = cur.fetchone()
                        feature_id = row[0] if row else None
                    item["layers"].append({
                        "standard_name": standard,
                        "central_layer_id": str((central_layers.get(standard) or {}).get("id") or ""),
                        "plan_layer_id": str(layer.get("id") or ""),
                        "manifest_layer_id": str((package.get(standard) or {}).get("id") or ""),
                        "feature_id": feature_id,
                        "policy": policy,
                    })
                report["projects"].append(item)

        self.stdout.write(json.dumps(report, ensure_ascii=False, default=str, sort_keys=True))
        if not report["projects"]:
            raise CommandError("target_photo_projects_not_found")
        for project in report["projects"]:
            for layer in project["layers"]:
                if not layer["policy"]:
                    raise CommandError("target_photo_policy_not_resolved")
                if not layer["manifest_layer_id"] or layer["manifest_layer_id"] != layer["plan_layer_id"]:
                    raise CommandError("qgis_manifest_definition_layer_id_mismatch")
        self.stdout.write("gis_photo_runtime_diagnostic=ok")
