from __future__ import annotations

import json
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geoflow_project.settings")

import django
django.setup()

from django.db import connections

from control.models import GroupDBConfig
from control.services.gis_admin import tenant_cursor
from control.services import gis_schema_manager as manager
from control.services import gis_schema_execution as execution

WATER_FIELDS = ("status", "date", "ang_dir")
SEWER_DROP_FIELDS = ("mng_cde", "ftr_idn", "gid", "off_cde", "hjd_cde", "bjd_cde", "sht_num")
SEWER_RENAMES = (("ist_ymd", "date"), ("sys_chk", "status"))
ALL_SEWER_FIELDS = tuple(dict.fromkeys(SEWER_DROP_FIELDS + tuple(x for pair in SEWER_RENAMES for x in pair)))

def rows(cur, query, params=None):
    cur.execute(query, params or [])
    names = [item[0] for item in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]

def field_refs(cur, field_id):
    if not field_id:
        return {}
    return manager.impact_for_field(cur, field_id)

with connections["default"].cursor() as cur:
    catalogs = rows(cur, """
        SELECT id::text,code,name
          FROM catalog.category_node
         WHERE level=2 AND active
         ORDER BY ord,code
    """)
    water_catalogs = [x for x in catalogs if "상수" in (x["name"] or "") or "WATER" in (x["code"] or "").upper()]
    sewer_catalogs = [x for x in catalogs if "하수" in (x["name"] or "") or "SEWER" in (x["code"] or "").upper()]
    if not water_catalogs or not sewer_catalogs:
        raise SystemExit("Required WATER/SEWER L2 catalogs were not found.")

    def domain_layers(catalog_rows):
        ids = [x["id"] for x in catalog_rows]
        return rows(cur, """
            SELECT DISTINCT l.id::text,l.standard_name,l.physical_name,l.label,l.active
              FROM gis.definition_layer l
              JOIN gis.definition_layer_catalog lc ON lc.layer_id=l.id
             WHERE lc.catalog_level=2 AND lc.catalog_item_id=ANY(%s::uuid[])
             ORDER BY l.standard_name
        """, [ids])

    water_layers = domain_layers(water_catalogs)
    sewer_layers = domain_layers(sewer_catalogs)

    def central_fields(layer_id, names):
        return rows(cur, """
            SELECT f.id::text,f.source_layer_id::text,f.physical_name,f.standard_name,f.label,
                   f.storage_data_type,f.storage_udt_name,f.max_length,f.precision,f.scale,
                   f.nullable,f.kind,f.widget_type,f.visible,f.form_visible,f.table_visible,
                   f.required,f.readonly,f.active
              FROM gis.definition_field f
             WHERE f.source_layer_id=%s AND f.physical_name=ANY(%s)
             ORDER BY f.physical_name,f.id
        """, [layer_id, list(names)])

    incomplete = rows(cur, """
        SELECT sc.id::text,sc.operation,sc.layer_id::text,sc.field_id::text,
               sc.old_name,sc.new_name,sc.old_type,sc.new_type,sc.status,sc.created_at
          FROM gis.schema_change sc
         WHERE sc.status IN ('PENDING','APPROVED','APPLYING','PARTIAL_APPLIED','PARTIAL_FAILED','FAILED')
         ORDER BY sc.created_at,sc.id
    """)

    inventory = {
        "catalogs": {"water": water_catalogs, "sewer": sewer_catalogs},
        "registered_tenants": [],
        "water": [],
        "sewer": [],
        "incomplete_schema_changes": incomplete,
    }

    tenant_configs = {
        str(x["group_id"]): {
            "tenant_group_id": str(x["group_id"]),
            "tenant_code": x["group__code"],
            "tenant_name": x["group__name"],
            "db_alias": x["db_alias"],
        }
        for x in GroupDBConfig.objects.using("default")
        .select_related("group")
        .filter(group__status="active")
        .exclude(db_alias="default")
        .values("group_id","group__code","group__name","db_alias")
    }
    inventory["registered_tenants"] = list(tenant_configs.values())

    for layer in water_layers:
        fields = central_fields(layer["id"], WATER_FIELDS)
        field_by_name = {}
        for f in fields:
            f["references"] = field_refs(cur, f["id"])
            f["incomplete_schema_changes"] = [
                x for x in incomplete if x["field_id"] == f["id"]
            ]
            field_by_name.setdefault(f["physical_name"], []).append(f)
        item = {**layer, "central_fields": field_by_name, "tenants": {}}
        for group_id, tenant in tenant_configs.items():
            t = {}
            with tenant_cursor(group_id, write=False) as tcur:
                for name in WATER_FIELDS:
                    t[name] = manager.tenant_column_state(
                        tcur, table_name=layer["physical_name"], column_name=name
                    )
            item["tenants"][group_id] = {"tenant": tenant, "columns": t}
        inventory["water"].append(item)

    for layer in sewer_layers:
        fields = central_fields(layer["id"], ALL_SEWER_FIELDS)
        field_by_name = {}
        for f in fields:
            f["references"] = field_refs(cur, f["id"])
            f["incomplete_schema_changes"] = [
                x for x in incomplete if x["field_id"] == f["id"]
            ]
            field_by_name.setdefault(f["physical_name"], []).append(f)
        rename_conflicts = {}
        for old_name, new_name in SEWER_RENAMES:
            rename_conflicts[old_name] = {
                "source_definitions": field_by_name.get(old_name, []),
                "target_definitions": field_by_name.get(new_name, []),
            }
        item = {
            **layer,
            "central_fields": field_by_name,
            "rename_conflicts": rename_conflicts,
            "tenants": {},
        }
        for group_id, tenant in tenant_configs.items():
            t = {}
            with tenant_cursor(group_id, write=False) as tcur:
                for name in ALL_SEWER_FIELDS:
                    t[name] = manager.tenant_column_state(
                        tcur, table_name=layer["physical_name"], column_name=name
                    )
            item["tenants"][group_id] = {"tenant": tenant, "columns": t}
        inventory["sewer"].append(item)

print("GIS_STANDARD_INVENTORY_JSON=" + json.dumps(inventory, ensure_ascii=False, default=str, sort_keys=True))
