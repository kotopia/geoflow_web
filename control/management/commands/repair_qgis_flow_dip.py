from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction

from control.models import GroupDBConfig
from control.services import gis_schema_manager as manager
from control.services.gis_admin import tenant_cursor
from geoflow_ops.gis.layer_plan import project_layer_plan
from geoflow_ops.gis.gpkg_syncable import build_syncable_project_geopackage_file
from geoflow_ops.gis.server_snapshot_cache import purge_project_server_snapshots


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

        # Physical DB rename is explicitly out of scope for this repair.
        # The operator has already renamed tenant gis.wtl_flow_ps.flow_dip -> flo_dip.
        # Refuse to mutate central metadata unless every existing target table proves
        # that the old column is gone and the new column exists.
        bad_physical=[
            state for state in tenant_states
            if state["table_exists"] and (state["old_exists"] or not state["new_exists"])
        ]
        if bad_physical:
            raise CommandError(
                "물리 DB는 수정하지 않습니다. tenant gis.wtl_flow_ps가 이미 flo_dip 상태여야 합니다: "
                + json.dumps(bad_physical,ensure_ascii=False)
            )

        project_definition_before=[]
        for cfg in GroupDBConfig.objects.using("default").select_related("group").filter(
            group__status="active"
        ).exclude(db_alias="default"):
            with tenant_cursor(cfg.group_id,write=False) as cur:
                cur.execute("SELECT to_regclass('gis.project_definition')")
                if cur.fetchone()[0] is None:
                    continue
                cur.execute(
                    """SELECT project_id::text,additions,private_items,overrides,definition_revision
                         FROM gis.project_definition
                        WHERE additions::text LIKE %s
                           OR private_items::text LIKE %s
                           OR overrides::text LIKE %s""",
                    [f"%{OLD_NAME}%",f"%{OLD_NAME}%",f"%{OLD_NAME}%"],
                )
                cols=[d[0] for d in cur.description]
                for row in cur.fetchall():
                    project_definition_before.append({
                        "group_id":str(cfg.group_id),
                        "tenant_name":cfg.group.name or cfg.group.code,
                        "alias":cfg.db_alias,
                        **dict(zip(cols,row)),
                    })
        report["project_definition_flow_dip_before"]=project_definition_before

        if not options["apply"]:
            return self._finish(report,options.get("report_file"))

        with transaction.atomic(using="default"):
            with connections["default"].cursor() as cur:
                before=manager.field_state(cur,field["id"])
                if not before:
                    raise CommandError("중앙 Definition field를 찾을 수 없습니다.")
                if before["physical_name"] == OLD_NAME:
                    cur.execute(
                        """UPDATE gis.definition_field
                              SET physical_name=%s,updated_at=now()
                            WHERE id=%s AND physical_name=%s""",
                        [NEW_NAME,field["id"],OLD_NAME],
                    )
                    if cur.rowcount != 1:
                        raise CommandError("중앙 Definition metadata update가 적용되지 않았습니다.")
                    manager.audit(
                        cur,
                        actor=actor,
                        target_type="FIELD",
                        target_id=field["id"],
                        change_type="METADATA_PHYSICAL_NAME_REPAIR",
                        before=before,
                        after=manager.field_state(cur,field["id"]),
                        schema_applied=False,
                    )
                elif before["physical_name"] != NEW_NAME:
                    raise CommandError(f"예상하지 못한 중앙 physical_name: {before['physical_name']}")

                # Close stale rename requests without executing tenant DDL.
                cur.execute(
                    """UPDATE gis.schema_change
                          SET status='CANCELLED'
                        WHERE field_id=%s AND operation='RENAME_COLUMN'
                          AND old_name=%s AND new_name=%s
                          AND status IN ('PENDING','APPROVED','PARTIAL_APPLIED','PARTIAL_FAILED','FAILED')""",
                    [field["id"],OLD_NAME,NEW_NAME],
                )
                report["cancelled_stale_schema_changes"]=cur.rowcount

        # project_definition normally references field UUIDs, not physical names.
        # If an old name survived inside GIS-owned JSON, replace only exact JSON
        # scalar values/keys; do not touch non-GIS schemas.
        def replace_exact(value):
            if isinstance(value,dict):
                return {
                    (NEW_NAME if key==OLD_NAME else key): replace_exact(item)
                    for key,item in value.items()
                }
            if isinstance(value,list):
                return [replace_exact(item) for item in value]
            if isinstance(value,str):
                return value.replace(OLD_NAME,NEW_NAME)
            return value

        project_definition_updates=[]
        for cfg in GroupDBConfig.objects.using("default").select_related("group").filter(
            group__status="active"
        ).exclude(db_alias="default"):
            with tenant_cursor(cfg.group_id,write=True) as cur:
                cur.execute("SELECT to_regclass('gis.project_definition')")
                if cur.fetchone()[0] is None:
                    continue
                cur.execute(
                    """SELECT project_id::text,additions,private_items,overrides
                         FROM gis.project_definition
                        WHERE additions::text LIKE %s
                           OR private_items::text LIKE %s
                           OR overrides::text LIKE %s
                        FOR UPDATE""",
                    [f"%{OLD_NAME}%",f"%{OLD_NAME}%",f"%{OLD_NAME}%"],
                )
                rows=cur.fetchall()
                for project_id,additions,private_items,overrides in rows:
                    old=(additions or {},private_items or {},overrides or {})
                    new=tuple(replace_exact(value) for value in old)
                    if new==old:
                        continue
                    cur.execute(
                        """UPDATE gis.project_definition
                              SET additions=%s::jsonb,private_items=%s::jsonb,
                                  overrides=%s::jsonb,definition_revision=NULL
                            WHERE project_id=%s""",
                        [
                            json.dumps(new[0],ensure_ascii=False),
                            json.dumps(new[1],ensure_ascii=False),
                            json.dumps(new[2],ensure_ascii=False),
                            project_id,
                        ],
                    )
                    project_definition_updates.append({
                        "tenant_name":cfg.group.name or cfg.group.code,
                        "alias":cfg.db_alias,
                        "project_id":project_id,
                    })
        report["project_definition_updates"]=project_definition_updates

        cache_purge=[]
        for cfg in GroupDBConfig.objects.using("default").select_related("group").filter(
            group__status="active"
        ).exclude(db_alias="default"):
            with tenant_cursor(cfg.group_id,write=False) as cur:
                cur.execute("SELECT to_regclass('prj.projects')")
                if cur.fetchone()[0] is None:
                    continue
                cur.execute("SELECT 1 FROM prj.projects WHERE id=%s",[PROJECT_ID])
                if not cur.fetchone():
                    continue
                removed=purge_project_server_snapshots(alias=cfg.db_alias,project_id=PROJECT_ID)
                cache_purge.append({
                    "tenant_name":cfg.group.name or cfg.group.code,
                    "alias":cfg.db_alias,
                    "project_id":PROJECT_ID,
                    "removed_files":removed,
                })
        report["snapshot_cache_purge"]=cache_purge

        with connections["default"].cursor() as cur:
            final=manager.field_state(cur,field["id"])
            cur.execute(
                """SELECT count(*) FROM gis.definition_field
                    WHERE source_layer_id=%s AND physical_name=%s""",
                [layer["id"],OLD_NAME],
            )
            central_old_count=int(cur.fetchone()[0])

        if not final or final["physical_name"]!=NEW_NAME:
            raise CommandError("중앙 Definition physical_name이 flo_dip로 정리되지 않았습니다.")
        if central_old_count:
            raise CommandError("중앙 Definition에 flow_dip 참조가 남아 있습니다.")
        report["field_after"]=final
        report["central_flow_dip_count"]=central_old_count

        tenant_after=[]
        for cfg in GroupDBConfig.objects.using("default").select_related("group").filter(group__status="active").exclude(db_alias="default"):
            with tenant_cursor(cfg.group_id,write=False) as cur:
                old_state=manager.tenant_column_state(cur,table_name=layer["physical_name"],column_name=OLD_NAME)
                new_state=manager.tenant_column_state(cur,table_name=layer["physical_name"],column_name=NEW_NAME)
                cur.execute("SELECT to_regclass('gis.project_definition')")
                pd_old_count=0
                if cur.fetchone()[0]:
                    cur.execute(
                        """SELECT count(*) FROM gis.project_definition
                            WHERE additions::text LIKE %s
                               OR private_items::text LIKE %s
                               OR overrides::text LIKE %s""",
                        [f"%{OLD_NAME}%",f"%{OLD_NAME}%",f"%{OLD_NAME}%"],
                    )
                    pd_old_count=int(cur.fetchone()[0])
            state={
                "group_id":str(cfg.group_id),
                "tenant_name":cfg.group.name or cfg.group.code,
                "alias":cfg.db_alias,
                "table_exists":bool(old_state.get("table_exists") or new_state.get("table_exists")),
                "old_exists":bool(old_state.get("column")),
                "new_exists":bool(new_state.get("column")),
                "project_definition_flow_dip_count":pd_old_count,
            }
            if state["table_exists"] and (state["old_exists"] or not state["new_exists"]):
                raise CommandError("tenant flow_dip/flo_dip schema mismatch: "+json.dumps(state,ensure_ascii=False))
            if pd_old_count:
                raise CommandError("project_definition에 flow_dip 참조가 남아 있습니다: "+json.dumps(state,ensure_ascii=False))
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
                form_json=json.dumps(plan.get("form_definition") or {},ensure_ascii=False,default=str)
                if OLD_NAME in form_json:
                    raise CommandError("Final Form Definition에 flow_dip 문자열이 남아 있습니다.")
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
                        "form_flow_dip_count":form_json.count(OLD_NAME),
                        "form_flo_dip_count":form_json.count(NEW_NAME),
                        "package_flow_dip_count":json.dumps(layer_meta,ensure_ascii=False,default=str).count(OLD_NAME),
                        "package_flo_dip_count":json.dumps(layer_meta,ensure_ascii=False,default=str).count(NEW_NAME),
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
