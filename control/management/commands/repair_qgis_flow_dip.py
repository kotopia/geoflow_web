from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from control.models import GroupDBConfig
from control.services import gis_schema_execution as execution
from control.services import gis_schema_manager as manager
from control.services.gis_admin import tenant_cursor
from geoflow_ops.gis.layer_plan import project_layer_plan
from geoflow_ops.gis.gpkg_syncable import build_syncable_project_geopackage_file


LAYER_STANDARD = "WTL_FLOW_PS"
OLD_NAME = "flow_dip"
NEW_NAME = "flo_dip"
PROJECT_ID = "86f52715-3cca-4124-9cc6-cb7c6a7e9c4e"


def _row(cur, query, params):
    cur.execute(query, params)
    row=cur.fetchone()
    if not row:
        return None
    cols=[d[0] for d in cur.description]
    return dict(zip(cols,row))


class Command(BaseCommand):
    help = "Repair stale WTL_FLOW_PS flow_dip -> flo_dip rollout and verify QGIS package materialization."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--report-file")

    def handle(self,*args,**options):
        actor="qgis-flow-dip-production-repair"
        report={"mode":"apply" if options["apply"] else "plan"}

        with connections["default"].cursor() as cur:
            layer=_row(cur,
                """SELECT id::text,standard_name,physical_name,label
                     FROM gis.definition_layer
                    WHERE standard_name=%s""",[LAYER_STANDARD])
            if not layer:
                raise CommandError("WTL_FLOW_PS 중앙 레이어를 찾을 수 없습니다.")

            field=_row(cur,
                """SELECT id::text,source_layer_id::text,physical_name,standard_name,label,
                          storage_data_type,active
                     FROM gis.definition_field
                    WHERE source_layer_id=%s AND physical_name IN (%s,%s)
                    ORDER BY CASE physical_name WHEN %s THEN 0 ELSE 1 END,id
                    LIMIT 1""",
                [layer["id"],OLD_NAME,NEW_NAME,OLD_NAME])
            if not field:
                raise CommandError("flow_dip/flo_dip 중앙 필드를 찾을 수 없습니다.")

            cur.execute(
                """SELECT id::text,operation,field_id::text,old_name,new_name,status,created_at
                     FROM gis.schema_change
                    WHERE field_id=%s AND operation='RENAME_COLUMN'
                      AND old_name=%s AND new_name=%s
                    ORDER BY created_at DESC,id DESC""",
                [field["id"],OLD_NAME,NEW_NAME])
            changes=[
                dict(zip([d[0] for d in cur.description],row))
                for row in cur.fetchall()
            ]

        tenant_states=[]
        for cfg in GroupDBConfig.objects.using("default").select_related("group").filter(group__status="active").exclude(db_alias="default"):
            with tenant_cursor(cfg.group_id,write=False) as cur:
                old_state=manager.tenant_column_state(cur,table_name=layer["physical_name"],column_name=OLD_NAME)
                new_state=manager.tenant_column_state(cur,table_name=layer["physical_name"],column_name=NEW_NAME)
            tenant_states.append({
                "group_id":str(cfg.group_id),
                "tenant_name":cfg.group.name or cfg.group.code,
                "alias":cfg.db_alias,
                "table_exists":bool(old_state.get("table_exists") or new_state.get("table_exists")),
                "old_exists":bool(old_state.get("column")),
                "new_exists":bool(new_state.get("column")),
            })

        report.update({"layer":layer,"field_before":field,"changes":changes,"tenant_before":tenant_states})

        if not options["apply"]:
            return self._finish(report,options.get("report_file"))

        if field["physical_name"] == OLD_NAME:
            reusable=next((x for x in changes if x["status"] in ("PENDING","APPROVED","PARTIAL_APPLIED","PARTIAL_FAILED","FAILED")),None)
            if reusable:
                change_id=reusable["id"]
            else:
                with connections["default"].cursor() as cur:
                    change_id,_=manager.ensure_rename_change(
                        cur,
                        field_id=field["id"],
                        layer_id=layer["id"],
                        old_name=OLD_NAME,
                        new_name=NEW_NAME,
                        actor=actor,
                    )
            result=execution.apply_rename_from_field_save(change_id,actor=actor)
            if result["status"]!="APPLIED":
                failures=execution.tenant_failure_details(change_id)
                raise CommandError("flow_dip rename repair failed: "+json.dumps(failures,ensure_ascii=False))
            report["repair_change_id"]=change_id
            report["repair_result"]=result
        elif field["physical_name"] != NEW_NAME:
            raise CommandError(f"예상하지 못한 중앙 physical_name: {field['physical_name']}")

        with connections["default"].cursor() as cur:
            final=manager.field_state(cur,field["id"])
        if not final or final["physical_name"]!=NEW_NAME:
            raise CommandError("중앙 Definition physical_name이 flo_dip로 finalize되지 않았습니다.")
        report["field_after"]=final

        tenant_after=[]
        for cfg in GroupDBConfig.objects.using("default").select_related("group").filter(group__status="active").exclude(db_alias="default"):
            with tenant_cursor(cfg.group_id,write=False) as cur:
                old_state=manager.tenant_column_state(cur,table_name=layer["physical_name"],column_name=OLD_NAME)
                new_state=manager.tenant_column_state(cur,table_name=layer["physical_name"],column_name=NEW_NAME)
            state={
                "group_id":str(cfg.group_id),
                "tenant_name":cfg.group.name or cfg.group.code,
                "alias":cfg.db_alias,
                "table_exists":bool(old_state.get("table_exists") or new_state.get("table_exists")),
                "old_exists":bool(old_state.get("column")),
                "new_exists":bool(new_state.get("column")),
            }
            if state["table_exists"] and (state["old_exists"] or not state["new_exists"]):
                raise CommandError("tenant flow_dip/flo_dip schema mismatch: "+json.dumps(state,ensure_ascii=False))
            tenant_after.append(state)
        report["tenant_after"]=tenant_after

        project_checks=[]
        for cfg in GroupDBConfig.objects.using("default").select_related("group").filter(group__status="active").exclude(db_alias="default"):
            built=None
            with tenant_cursor(cfg.group_id,write=False) as cur:
                cur.execute("SELECT to_regclass('prj.projects')")
                if cur.fetchone()[0] is None:
                    continue
                cur.execute("SELECT code,name FROM prj.projects WHERE id=%s",[PROJECT_ID])
                row=cur.fetchone()
                if not row:
                    continue

                # tenant_cursor owns the dynamic Django alias lifetime. Keep
                # every helper using connections[cfg.db_alias] inside this context.
                plan=project_layer_plan(cfg.db_alias,PROJECT_ID)
                matching=[
                    {
                        "id":f.get("id"),"layer_id":f.get("layer_id"),
                        "field_name":f.get("field_name"),
                        "storage_data_type":f.get("storage_data_type"),
                    }
                    for f in (plan.get("form_definition") or {}).get("fields",[])
                    if str(f.get("field_name") or "") in (OLD_NAME,NEW_NAME)
                ]
                if any(x["field_name"]==OLD_NAME for x in matching):
                    raise CommandError("Final Form Definition에 flow_dip가 남아 있습니다.")
                if not any(x["field_name"]==NEW_NAME for x in matching):
                    raise CommandError("Final Form Definition에 flo_dip가 없습니다.")

                try:
                    built,layer_meta,snapshot_revision=build_syncable_project_geopackage_file(
                        cfg.db_alias,project_id=PROJECT_ID,plan=plan
                    )
                    project_checks.append({
                        "tenant_name":cfg.group.name or cfg.group.code,
                        "alias":cfg.db_alias,
                        "project_code":row[0],
                        "project_name":row[1],
                        "definition_revision":(plan.get("definition") or {}).get("revision"),
                        "matching_fields":matching,
                        "package_layers":len(layer_meta),
                        "package_bytes":built.stat().st_size,
                        "snapshot_revision":snapshot_revision,
                        "status":"SUCCESS",
                    })
                finally:
                    if built is not None:
                        built.unlink(missing_ok=True)

        if not project_checks:
            raise CommandError("검증 대상 QGIS 프로젝트를 찾지 못했습니다.")
        report["qgis_project_checks"]=project_checks
        self._finish(report,options.get("report_file"))

    def _finish(self,report,path):
        rendered=json.dumps(report,ensure_ascii=False,default=str,sort_keys=True)
        self.stdout.write("QGIS_FLOW_DIP_REPAIR_JSON="+rendered)
        if path:
            target=Path(path)
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(rendered+"\n",encoding="utf-8")
