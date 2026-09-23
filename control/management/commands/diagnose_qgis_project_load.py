from __future__ import annotations

import json
import traceback
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from control.models import GroupDBConfig
from control.services.gis_admin import tenant_cursor
from geoflow_ops.gis import central_definitions, layer_plan
from geoflow_ops.gis.gpkg import project_geopackage_layer_manifest
from geoflow_ops.gis.gpkg_syncable import build_syncable_project_geopackage_file
from geoflow_ops.gis.qgis_manifest import build_qgis_manifest
from geoflow_ops.gis.reference_catalog import project_reference_catalog


OLD_NAMES = {"ist_ymd", "sys_chk"}
REMOVED_NAMES = {"mng_cde", "ftr_idn", "gid", "off_cde", "hjd_cde", "bjd_cde", "sht_num"}


def _canon_type(row):
    raw = str(row.get("data_type") or row.get("udt_name") or "").lower()
    if raw in ("character varying", "varchar"):
        length = row.get("character_maximum_length")
        return f"varchar({length})" if length else "varchar"
    if raw in ("integer", "int4"):
        return "integer"
    if raw in ("bigint", "int8"):
        return "bigint"
    if raw == "numeric":
        p = row.get("numeric_precision")
        s = row.get("numeric_scale")
        return f"numeric({p},{s})" if p is not None and s is not None else "numeric"
    return raw


class Command(BaseCommand):
    help = "Read-only production diagnostic for QGIS project load materialization."

    def handle(self, *args, **options):
        definition = central_definitions.central_snapshot()
        if definition is None:
            raise CommandError("central_definition_unavailable")

        central_field_ids = {str(f["id"]) for f in definition.get("fields", [])}
        report = {
            "definition_revision": (definition.get("definition") or {}).get("revision")
                or definition.get("revision") or "",
            "tenants": [],
            "failures": [],
            "project_success": [],
        }

        configs = list(
            GroupDBConfig.objects.using("default")
            .select_related("group")
            .filter(group__status="active")
            .exclude(db_alias="default")
            .order_by("group_id")
        )

        for config in configs:
            tenant = {
                "group_id": str(config.group_id),
                "name": str(config.group.name or config.group.code),
                "alias": config.db_alias,
                "projects": [],
            }
            report["tenants"].append(tenant)
            try:
                with tenant_cursor(config.group_id, write=False) as cur:
                    cur.execute("SELECT to_regclass('prj.scope_item'),to_regclass('prj.projects')")
                    rel = cur.fetchone()
                    if not rel or not all(rel):
                        tenant["status"] = "NO_PROJECT_SCHEMA"
                        continue

                    scopes_by_project = defaultdict(list)
                    for project_id, lv2, lv3, lv4 in layer_plan._scope_rows(cur):
                        scopes_by_project[str(project_id)].append(
                            {"2": lv2, "3": lv3, "4": lv4}
                        )

                for project_id, scopes in scopes_by_project.items():
                    item = {"project_id": project_id, "stages": {}}
                    tenant["projects"].append(item)
                    try:
                        with tenant_cursor(config.group_id, write=False) as cur:
                            cur.execute("SELECT code,name FROM prj.projects WHERE id=%s", [project_id])
                            row = cur.fetchone()
                            if not row:
                                item["status"] = "PROJECT_ROW_MISSING"
                                continue
                            item["project_code"] = row[0]
                            item["project_name"] = row[1]
                            cfg = central_definitions.project_config(cur, project_id)

                        cfg_text = json.dumps(cfg, ensure_ascii=False, default=str)
                        item["stale_project_definition_names"] = sorted(
                            name for name in OLD_NAMES | REMOVED_NAMES if name in cfg_text
                        )
                        ids_in_cfg = set()
                        for container in (cfg.get("additions") or {}, cfg.get("private_items") or {}, cfg.get("overrides") or {}):
                            ids_in_cfg.update(str(k) for k in container.keys())
                        item["stale_project_definition_field_ids"] = sorted(ids_in_cfg - central_field_ids)

                        ids = layer_plan._resolved_layer_ids(definition, scopes, cfg)
                        layers = [
                            row for row in definition["layers"]
                            if row["id"] in ids and row.get("active")
                        ]
                        if not layers:
                            item["status"] = "NO_ENABLED_LAYERS"
                            continue

                        final_form = central_definitions.resolve(definition, cfg, layers)
                        item["stages"]["final_form"] = {
                            "ok": True,
                            "revision": final_form.get("revision"),
                            "field_count": len(final_form.get("fields") or []),
                        }
                        bad_names = sorted({
                            str(f.get("field_name") or "")
                            for f in final_form.get("fields") or []
                            if str(f.get("field_name") or "") in OLD_NAMES | REMOVED_NAMES
                        })
                        item["final_form_stale_names"] = bad_names

                        plan = layer_plan.project_layer_plan(config.db_alias, project_id)
                        item["stages"]["layer_plan"] = {
                            "ok": bool(plan.get("ready")),
                            "gis_enabled": bool(plan.get("gis_enabled")),
                            "layer_count": len(plan.get("layers") or []),
                            "definition_revision": (plan.get("definition") or {}).get("revision") or "",
                        }
                        if not plan.get("ready") or not plan.get("gis_enabled"):
                            item["status"] = "PLAN_NOT_READY"
                            continue

                        missing = []
                        mismatched = []
                        with tenant_cursor(config.group_id, write=False) as cur:
                            for layer in plan.get("layers") or []:
                                table = str(layer.get("physical_name") or "")
                                cur.execute("SELECT to_regclass(%s)", [f"gis.{table}"])
                                if cur.fetchone()[0] is None:
                                    missing.append({"layer": table, "reason": "table_missing"})
                                    continue
                                cur.execute(
                                    """SELECT column_name,data_type,udt_name,character_maximum_length,
                                              numeric_precision,numeric_scale
                                         FROM information_schema.columns
                                        WHERE table_schema='gis' AND table_name=%s""",
                                    [table],
                                )
                                dbcols = {}
                                for r in cur.fetchall():
                                    dbcols[r[0]] = {
                                        "data_type": r[1], "udt_name": r[2],
                                        "character_maximum_length": r[3],
                                        "numeric_precision": r[4], "numeric_scale": r[5],
                                    }
                                layer_id = str(layer.get("id") or "")
                                for field in (plan.get("form_definition") or {}).get("fields", []):
                                    if str(field.get("layer_id") or "") != layer_id:
                                        continue
                                    storage = field.get("storage") or {}
                                    if storage.get("kind") != "column":
                                        continue
                                    name = str(field.get("field_name") or "")
                                    if not name or name == "geom":
                                        continue
                                    if name not in dbcols:
                                        missing.append({"layer": table, "field": name, "field_id": field.get("id")})
                                        continue
                                    expected = str(field.get("storage_data_type") or "")
                                    actual = _canon_type(dbcols[name])
                                    if expected and expected not in (actual, dbcols[name]["data_type"], dbcols[name]["udt_name"]):
                                        mismatched.append({
                                            "layer": table, "field": name, "field_id": field.get("id"),
                                            "expected": expected, "actual": actual,
                                        })
                        item["missing_physical_fields"] = missing
                        item["type_mismatches"] = mismatched

                        refs = project_reference_catalog(
                            using=config.db_alias,
                            standard_names=[x.get("standard_name") for x in plan.get("layers") or []],
                        )
                        item["stages"]["reference_catalog"] = {
                            "ok": bool(refs.get("ok", True)),
                            "binding_count": refs.get("binding_count"),
                            "group_count": refs.get("group_count"),
                        }

                        package_layers = project_geopackage_layer_manifest(config.db_alias, plan)
                        item["stages"]["package_manifest"] = {
                            "ok": True,
                            "layer_count": len(package_layers),
                        }

                        manifest = build_qgis_manifest(
                            project={
                                "id": project_id,
                                "code": item.get("project_code") or "",
                                "name": item.get("project_name") or "",
                                "status": "",
                            },
                            plan=plan,
                            can_write=True,
                            package_url=f"/gis/projects/{project_id}/api/qgis-package/",
                            package_layers=package_layers,
                            layer_counts={},
                            sync_url=f"/gis/projects/{project_id}/api/qgis-sync/",
                            changeset_url=f"/gis/projects/{project_id}/api/changesets/",
                            delta_url=f"/gis/projects/{project_id}/api/delta/",
                            changeset_supported=True,
                        )
                        item["stages"]["qgis_manifest"] = {
                            "ok": True,
                            "manifest_version": manifest.get("manifest_version"),
                            "form_definition_revision": manifest.get("transport", {}).get("form_definition_revision"),
                        }

                        built_path = None
                        try:
                            built_path, layer_meta, snapshot_revision = build_syncable_project_geopackage_file(
                                config.db_alias,
                                project_id=project_id,
                                plan=plan,
                            )
                            item["stages"]["package_build"] = {
                                "ok": True,
                                "layer_count": len(layer_meta),
                                "snapshot_revision": snapshot_revision,
                                "bytes": built_path.stat().st_size,
                            }
                        finally:
                            if built_path is not None:
                                built_path.unlink(missing_ok=True)

                        item["status"] = "SUCCESS"
                        report["project_success"].append({
                            "tenant": tenant["name"], "project_id": project_id,
                        })
                    except Exception as exc:
                        item["status"] = "FAIL"
                        failure = {
                            "tenant": tenant["name"],
                            "alias": config.db_alias,
                            "project_id": project_id,
                            "project_code": item.get("project_code"),
                            "project_name": item.get("project_name"),
                            "exception_type": type(exc).__name__,
                            "message": str(exc),
                            "traceback": traceback.format_exc(limit=12),
                            "stages": item.get("stages"),
                            "missing_physical_fields": item.get("missing_physical_fields"),
                            "type_mismatches": item.get("type_mismatches"),
                            "stale_project_definition_names": item.get("stale_project_definition_names"),
                            "stale_project_definition_field_ids": item.get("stale_project_definition_field_ids"),
                        }
                        report["failures"].append(failure)
            except Exception as exc:
                report["failures"].append({
                    "tenant": tenant["name"],
                    "alias": config.db_alias,
                    "project_id": None,
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                    "traceback": traceback.format_exc(limit=12),
                })

        self.stdout.write("QGIS_PROJECT_LOAD_DIAG_JSON=" + json.dumps(report, ensure_ascii=False, default=str, sort_keys=True))
        if report["failures"]:
            raise CommandError(f"qgis_project_load_failures={len(report['failures'])}")
        self.stdout.write("RESULT qgis_project_load_diagnostic=SUCCESS")
