from __future__ import annotations
import json, os
os.environ.setdefault("DJANGO_SETTINGS_MODULE","geoflow_project.settings")
import django
django.setup()
from django.db import connections
from control.models import GroupDBConfig
from control.services.gis_admin import tenant_cursor
from geoflow_ops.gis import central_definitions, layer_plan

PROJECT_ID="86f52715-3cca-4124-9cc6-cb7c6a7e9c4e"
TARGET_NAMES={"flow_dip","flo_dip"}

definition=central_definitions.central_snapshot() or {}
result={"project_id":PROJECT_ID,"definition_revision":(definition.get("definition") or {}).get("revision") or definition.get("revision"),"central_fields":[],"tenants":[]}

for f in definition.get("fields",[]):
    if str(f.get("physical_name") or "") in TARGET_NAMES or str(f.get("field_name") or "") in TARGET_NAMES:
        result["central_fields"].append({
            "id":f.get("id"),
            "source_layer_id":f.get("source_layer_id"),
            "physical_name":f.get("physical_name"),
            "standard_name":f.get("standard_name"),
            "active":f.get("active"),
            "storage_data_type":f.get("storage_data_type"),
        })

for cfg in GroupDBConfig.objects.using("default").select_related("group").filter(group__status="active").exclude(db_alias="default"):
    tenant={"group_id":str(cfg.group_id),"name":cfg.group.name,"alias":cfg.db_alias}
    try:
        with tenant_cursor(cfg.group_id,write=False) as cur:
            cur.execute("SELECT to_regclass('prj.projects')")
            if cur.fetchone()[0] is None:
                tenant["project_found"]=False
                result["tenants"].append(tenant); continue
            cur.execute("SELECT code,name FROM prj.projects WHERE id=%s",[PROJECT_ID])
            row=cur.fetchone()
            tenant["project_found"]=bool(row)
            if not row:
                result["tenants"].append(tenant); continue
            tenant["project_code"],tenant["project_name"]=row
            config=central_definitions.project_config(cur,PROJECT_ID)
            tenant["project_definition"]=config
            plan=layer_plan.project_layer_plan(cfg.db_alias,PROJECT_ID)
            tenant["plan_ready"]=plan.get("ready")
            tenant["gis_enabled"]=plan.get("gis_enabled")
            tenant["plan_definition"]=plan.get("definition")
            tenant["layers"]=[{"id":x.get("id"),"standard_name":x.get("standard_name"),"physical_name":x.get("physical_name")} for x in plan.get("layers") or []]
            ff=plan.get("form_definition") or {}
            tenant["form_revision"]=ff.get("revision")
            tenant["matching_form_fields"]=[
                {
                    "id":f.get("id"),"layer_id":f.get("layer_id"),"field_name":f.get("field_name"),
                    "physical_name":f.get("physical_name"),"storage_data_type":f.get("storage_data_type"),
                    "active":f.get("active"),"storage":f.get("storage"),
                }
                for f in ff.get("fields") or []
                if str(f.get("field_name") or "") in TARGET_NAMES or str(f.get("physical_name") or "") in TARGET_NAMES
            ]
            tables={x.get("physical_name") for x in plan.get("layers") or [] if x.get("physical_name")}
            tenant["physical"]={}
            for table in sorted(tables):
                cur.execute("SELECT to_regclass(%s)",[f"gis.{table}"])
                if cur.fetchone()[0] is None: continue
                cur.execute("""SELECT column_name,data_type,udt_name,character_maximum_length,numeric_precision,numeric_scale
                               FROM information_schema.columns WHERE table_schema='gis' AND table_name=%s
                                 AND column_name IN ('flow_dip','flo_dip') ORDER BY column_name""",[table])
                rows=cur.fetchall()
                if rows:
                    tenant["physical"][table]=[
                        {"column_name":r[0],"data_type":r[1],"udt_name":r[2],"max_length":r[3],"precision":r[4],"scale":r[5]}
                        for r in rows
                    ]
    except Exception as exc:
        tenant["error"]=type(exc).__name__+": "+str(exc)
    result["tenants"].append(tenant)

with connections["default"].cursor() as cur:
    cur.execute("""SELECT sc.id::text,sc.operation,sc.field_id::text,sc.old_name,sc.new_name,sc.status,sc.created_at,
                          f.physical_name,f.standard_name,l.standard_name,l.physical_name
                   FROM gis.schema_change sc
                   LEFT JOIN gis.definition_field f ON f.id=sc.field_id
                   JOIN gis.definition_layer l ON l.id=sc.layer_id
                   WHERE sc.old_name IN ('flow_dip','flo_dip') OR sc.new_name IN ('flow_dip','flo_dip')
                   ORDER BY sc.created_at""")
    cols=[d[0] for d in cur.description]
    result["schema_changes"]=[dict(zip(cols,r)) for r in cur.fetchall()]

print("QGIS_FLOW_DIP_DIAG_JSON="+json.dumps(result,ensure_ascii=False,default=str,sort_keys=True))
