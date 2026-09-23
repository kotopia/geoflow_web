from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction

from control.services import gis_definitions as definitions
from control.services import gis_schema_execution as execution
from control.services import gis_schema_manager as manager
from control.services.gis_admin import tenant_cursor


WATER_CODE = "WATER"
SEWER_CODE = "SEWERAGE"
WATER_FIELDS = ("status", "date", "ang_dir")
SEWER_DROP_FIELDS = ("mng_cde", "ftr_idn", "gid", "off_cde", "hjd_cde", "bjd_cde", "sht_num")
SEWER_RENAMES = (("ist_ymd", "date"), ("sys_chk", "status"))
INCOMPLETE = ("PENDING", "APPROVED", "APPLYING", "PARTIAL_APPLIED", "PARTIAL_FAILED", "FAILED")


def _rows(cur, query, params=None):
    cur.execute(query, params or [])
    names = [item[0] for item in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def _catalog(cur, code):
    cur.execute(
        "SELECT id::text,code,name FROM catalog.category_node WHERE level=2 AND active AND code=%s",
        [code],
    )
    row = cur.fetchone()
    if not row:
        raise CommandError(f"Catalog {code}를 찾을 수 없습니다.")
    return {"id": row[0], "code": row[1], "name": row[2]}


def _layers(cur, catalog_id, prefix):
    return _rows(
        cur,
        """SELECT DISTINCT l.id::text,l.standard_name,l.physical_name,l.label
             FROM gis.definition_layer l
             JOIN gis.definition_layer_catalog lc ON lc.layer_id=l.id
            WHERE lc.catalog_level=2 AND lc.catalog_item_id=%s
              AND l.standard_name LIKE %s
            ORDER BY l.standard_name""",
        [catalog_id, prefix + "%"],
    )


def _field(cur, layer_id, physical_name):
    rows = _rows(
        cur,
        """SELECT id::text,source_layer_id::text,physical_name,standard_name,label,
                  storage_data_type,storage_udt_name,max_length,precision,scale,
                  nullable,storage_default,kind,widget_type,visible,form_visible,
                  table_visible,required,readonly,sort_order,unit,description,active
             FROM gis.definition_field
            WHERE source_layer_id=%s AND physical_name=%s
            ORDER BY id""",
        [layer_id, physical_name],
    )
    if len(rows) > 1:
        raise CommandError(f"{layer_id}:{physical_name} 중앙 Definition이 중복입니다.")
    return rows[0] if rows else None


def _field_type(field):
    return manager.storage_type(
        db_type=field.get("storage_data_type") or field.get("storage_udt_name") or "text",
        max_length=field.get("max_length"),
        precision=field.get("precision"),
        scale=field.get("scale"),
    )


def _cancel_change(cur, change_id, actor, reason):
    cur.execute(
        """UPDATE gis.schema_change
              SET status='CANCELLED'
            WHERE id=%s AND status=ANY(%s)
        RETURNING id::text""",
        [change_id, list(INCOMPLETE)],
    )
    if cur.fetchone():
        manager.audit(
            cur,
            actor=actor,
            target_type="SCHEMA",
            target_id=change_id,
            change_type="CANCEL_STALE_SCHEMA_CHANGE",
            after={"reason": reason},
        )
        return True
    return False


def _cleanup_stale_requests(cur, actor):
    changes = _rows(
        cur,
        """SELECT sc.id::text,sc.operation,sc.field_id::text,sc.old_name,sc.new_name,
                  sc.new_type,sc.status,sc.created_at,f.physical_name,f.active
             FROM gis.schema_change sc
             LEFT JOIN gis.definition_field f ON f.id=sc.field_id
            WHERE sc.status=ANY(%s)
            ORDER BY sc.created_at DESC,sc.id DESC""",
        [list(INCOMPLETE)],
    )
    cancelled = []
    seen = set()
    for change in changes:
        key = (
            change["field_id"], change["operation"], change["old_name"],
            change["new_name"], change["new_type"],
        )
        if key in seen:
            if _cancel_change(cur, change["id"], actor, "duplicate incomplete schema change"):
                cancelled.append(change["id"])
            continue
        seen.add(key)

        if not change["field_id"] or change["physical_name"] is None:
            continue
        if change["operation"] in ("RENAME_COLUMN", "ALTER_TYPE", "DROP_COLUMN"):
            if change["old_name"] and change["physical_name"] != change["old_name"]:
                if _cancel_change(cur, change["id"], actor, "field physical_name no longer matches old_name"):
                    cancelled.append(change["id"])
        elif change["operation"] == "ADD_COLUMN" and change["active"]:
            if change["new_name"] == change["physical_name"]:
                if _cancel_change(cur, change["id"], actor, "field is already active"):
                    cancelled.append(change["id"])
    return cancelled


def _find_change(cur, *, field_id, operation, old_name=None, new_name=None, new_type=None):
    cur.execute(
        """SELECT id::text,status
             FROM gis.schema_change
            WHERE field_id=%s AND operation=%s
              AND old_name IS NOT DISTINCT FROM %s
              AND new_name IS NOT DISTINCT FROM %s
              AND new_type IS NOT DISTINCT FROM %s
              AND status=ANY(%s)
            ORDER BY created_at DESC,id DESC
            LIMIT 1""",
        [field_id, operation, old_name, new_name, new_type, list(INCOMPLETE)],
    )
    row = cur.fetchone()
    return {"id": row[0], "status": row[1]} if row else None


def _apply_existing_change(change_id, actor, *, allow_data_loss=False, confirmation=""):
    change = execution.get_change(change_id)
    if change["status"] in ("PENDING", "FAILED", "PARTIAL_FAILED"):
        execution.approve(change_id, actor=actor, allow_data_loss=allow_data_loss)
    result = execution.apply(
        change_id,
        execution.registered_tenant_ids(),
        actor=actor,
        confirmation=confirmation,
    )
    if result["status"] != "APPLIED":
        failures = execution.tenant_failure_details(change_id)
        detail = "; ".join(f"{x['tenant_name']}: {x['error']}" for x in failures)
        raise CommandError(f"Schema 변경 {change_id} 실패: {result['status']} {detail}")
    return result


def _activate_water_field(cur, layer, field, actor):
    type_value = _field_type(field)
    existing = _find_change(
        cur,
        field_id=field["id"],
        operation="ADD_COLUMN",
        new_name=field["physical_name"],
        new_type=type_value,
    )
    if existing:
        change_id = existing["id"]
    else:
        change_id = manager.create_schema_change(
            cur,
            {
                "operation": "ADD_COLUMN",
                "layer_id": layer["id"],
                "field_id": field["id"],
                "new_name": field["physical_name"],
                "new_type": type_value,
            },
            actor=actor,
        )
    return change_id


def _check_rename_conflicts(layer, old_name, new_name):
    conflicts = []
    for group_id in execution.registered_tenant_ids():
        with tenant_cursor(group_id, write=False) as cur:
            source = manager.tenant_column_state(cur, table_name=layer["physical_name"], column_name=old_name)
            target = manager.tenant_column_state(cur, table_name=layer["physical_name"], column_name=new_name)
        if source.get("table_exists") and source.get("column") and target.get("column"):
            conflicts.append(group_id)
    if conflicts:
        raise CommandError(
            f"{layer['standard_name']} {old_name}→{new_name}: source/target 컬럼이 동시에 존재하는 tenant가 있습니다: "
            + ",".join(conflicts)
        )


def _delete_field_definition(cur, field, actor, applied_change_id):
    before = manager.field_state(cur, field["id"])

    cur.execute(
        "SELECT id::text FROM gis.definition_rule WHERE source_field=%s OR target_field=%s",
        [field["id"], field["id"]],
    )
    rule_ids = [row[0] for row in cur.fetchall()]
    if rule_ids:
        cur.execute("DELETE FROM gis.definition_rule_value WHERE rule_id=ANY(%s::uuid[])", [rule_ids])
        cur.execute("DELETE FROM gis.definition_rule WHERE id=ANY(%s::uuid[])", [rule_ids])

    cur.execute("DELETE FROM gis.definition_code WHERE field_id=%s", [field["id"]])
    cur.execute("DELETE FROM gis.definition_group_field WHERE field_id=%s", [field["id"]])
    cur.execute("DELETE FROM gis.definition_field_layer WHERE field_id=%s", [field["id"]])

    cur.execute(
        """UPDATE gis.schema_change
              SET status='CANCELLED'
            WHERE field_id=%s AND id<>%s AND status=ANY(%s)""",
        [field["id"], applied_change_id, list(INCOMPLETE)],
    )
    cur.execute("UPDATE gis.schema_change SET field_id=NULL WHERE field_id=%s", [field["id"]])
    cur.execute("DELETE FROM gis.definition_field WHERE id=%s", [field["id"]])

    manager.audit(
        cur,
        actor=actor,
        target_type="FIELD",
        target_id=field["id"],
        change_type="DROP_FIELD_CLEANUP",
        before=before,
        after=None,
        schema_applied=True,
    )


class Command(BaseCommand):
    help = "Normalize WATER/SEWER test GIS definitions and tenant gis.* schemas."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--report-file")

    def handle(self, *args, **options):
        apply_mode = bool(options["apply"])
        actor = "gis-standard-cleanup"
        report = {
            "mode": "apply" if apply_mode else "plan",
            "stale_cancelled": [],
            "water": [],
            "sewer_renames": [],
            "sewer_drops": [],
            "validation": {},
        }

        with connections["default"].cursor() as cur:
            water = _catalog(cur, WATER_CODE)
            sewer = _catalog(cur, SEWER_CODE)
            water_layers = _layers(cur, water["id"], "WTL_")
            sewer_layers = _layers(cur, sewer["id"], "SWL_")

        if not apply_mode:
            report["water_layers"] = water_layers
            report["sewer_layers"] = sewer_layers
            self._write_report(report, options.get("report_file"))
            return

        with transaction.atomic(using="default"):
            with connections["default"].cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(hashtext('geoflow.central.gis.standard-cleanup'))")
                report["stale_cancelled"] = _cleanup_stale_requests(cur, actor)

        # STEP 3: WATER inactive fields -> apply/reuse ADD_COLUMN and activate only after tenant success.
        for layer in water_layers:
            for name in WATER_FIELDS:
                with connections["default"].cursor() as cur:
                    field = _field(cur, layer["id"], name)
                    if not field or field["active"]:
                        continue
                    change_id = _activate_water_field(cur, layer, field, actor)
                _apply_existing_change(change_id, actor)
                report["water"].append({
                    "layer": layer["standard_name"],
                    "field": name,
                    "field_id": field["id"],
                    "change_id": change_id,
                    "status": "APPLIED",
                })

        # STEP 4: SEWER rename before deletes.
        for layer in sewer_layers:
            for old_name, new_name in SEWER_RENAMES:
                with connections["default"].cursor() as cur:
                    source = _field(cur, layer["id"], old_name)
                    target = _field(cur, layer["id"], new_name)
                if not source:
                    report["sewer_renames"].append({
                        "layer": layer["standard_name"],
                        "source": old_name,
                        "target": new_name,
                        "status": "NOT_APPLICABLE",
                    })
                    continue
                if target and target["id"] != source["id"]:
                    raise CommandError(
                        f"{layer['standard_name']} {old_name}→{new_name}: 중앙 target Definition 충돌"
                    )
                _check_rename_conflicts(layer, old_name, new_name)
                with connections["default"].cursor() as cur:
                    change_id, _ = manager.ensure_rename_change(
                        cur,
                        field_id=source["id"],
                        layer_id=layer["id"],
                        old_name=old_name,
                        new_name=new_name,
                        actor=actor,
                    )
                result = execution.apply_rename_from_field_save(change_id, actor=actor)
                if result["status"] != "APPLIED":
                    raise CommandError(f"{layer['standard_name']} rename 실패: {result}")
                report["sewer_renames"].append({
                    "layer": layer["standard_name"],
                    "source": old_name,
                    "target": new_name,
                    "field_id": source["id"],
                    "change_id": change_id,
                    "status": "APPLIED",
                })

        # STEP 5: SEWER physical DROP + central definition cleanup.
        for layer in sewer_layers:
            for name in SEWER_DROP_FIELDS:
                with connections["default"].cursor() as cur:
                    field = _field(cur, layer["id"], name)
                if not field:
                    continue
                with transaction.atomic(using="default"):
                    with connections["default"].cursor() as cur:
                        current = manager.field_state(cur, field["id"])
                        if current and current["active"]:
                            manager.mutate_admin(
                                cur,
                                {"action": "deactivate_field_admin", "id": field["id"]},
                                actor=actor,
                            )
                        existing = _find_change(
                            cur,
                            field_id=field["id"],
                            operation="DROP_COLUMN",
                            old_name=name,
                        )
                        change_id = (
                            existing["id"] if existing else
                            manager.create_schema_change(
                                cur,
                                {
                                    "operation": "DROP_COLUMN",
                                    "layer_id": layer["id"],
                                    "field_id": field["id"],
                                    "old_name": name,
                                },
                                actor=actor,
                            )
                        )
                _apply_existing_change(
                    change_id,
                    actor,
                    allow_data_loss=True,
                    confirmation="DROP COLUMN " + name,
                )
                with transaction.atomic(using="default"):
                    with connections["default"].cursor() as cur:
                        _delete_field_definition(cur, field, actor, change_id)
                report["sewer_drops"].append({
                    "layer": layer["standard_name"],
                    "field": name,
                    "field_id": field["id"],
                    "change_id": change_id,
                    "status": "APPLIED",
                })

        # STEP 6: central + tenant invariants.
        validation = {"water": [], "sewer": []}
        with connections["default"].cursor() as cur:
            for layer in water_layers:
                for name in WATER_FIELDS:
                    field = _field(cur, layer["id"], name)
                    if not field:
                        continue
                    if not field["active"]:
                        raise CommandError(f"{layer['standard_name']}.{name} 중앙 active=false")
                    for group_id in execution.registered_tenant_ids():
                        with tenant_cursor(group_id, write=False) as tcur:
                            state = manager.tenant_column_state(
                                tcur, table_name=layer["physical_name"], column_name=name
                            )
                        if state["table_exists"] and not state["column"]:
                            raise CommandError(
                                f"{layer['standard_name']}.{name} tenant {group_id} 컬럼 누락"
                            )
                    validation["water"].append(f"{layer['standard_name']}.{name}")

            for layer in sewer_layers:
                for name in SEWER_DROP_FIELDS:
                    if _field(cur, layer["id"], name):
                        raise CommandError(f"{layer['standard_name']}.{name} 중앙 Definition 잔존")
                    for group_id in execution.registered_tenant_ids():
                        with tenant_cursor(group_id, write=False) as tcur:
                            state = manager.tenant_column_state(
                                tcur, table_name=layer["physical_name"], column_name=name
                            )
                        if state["table_exists"] and state["column"]:
                            raise CommandError(
                                f"{layer['standard_name']}.{name} tenant {group_id} DROP 미완료"
                            )

                for old_name, new_name in SEWER_RENAMES:
                    old_field = _field(cur, layer["id"], old_name)
                    new_field = _field(cur, layer["id"], new_name)
                    if old_field:
                        raise CommandError(f"{layer['standard_name']}.{old_name} 중앙 old name 잔존")
                    if new_field:
                        for group_id in execution.registered_tenant_ids():
                            with tenant_cursor(group_id, write=False) as tcur:
                                old_state = manager.tenant_column_state(
                                    tcur, table_name=layer["physical_name"], column_name=old_name
                                )
                                new_state = manager.tenant_column_state(
                                    tcur, table_name=layer["physical_name"], column_name=new_name
                                )
                            if old_state["table_exists"] and old_state["column"]:
                                raise CommandError(
                                    f"{layer['standard_name']}.{old_name} tenant {group_id} old 컬럼 잔존"
                                )
                            if new_state["table_exists"] and not new_state["column"]:
                                raise CommandError(
                                    f"{layer['standard_name']}.{new_name} tenant {group_id} target 컬럼 누락"
                                )
                        validation["sewer"].append(f"{layer['standard_name']}.{new_name}")

            snapshot = definitions.snapshot(cur)
            active_fields = {
                (f.get("source_layer"), f.get("physical_name"))
                for f in snapshot["fields"] if f.get("active", True)
            }
            for layer in sewer_layers:
                for name in SEWER_DROP_FIELDS + tuple(x[0] for x in SEWER_RENAMES):
                    if (layer["standard_name"], name) in active_fields:
                        raise CommandError(f"Final Definition에 제거 대상이 남아 있습니다: {layer['standard_name']}.{name}")

        report["validation"] = validation
        self._write_report(report, options.get("report_file"))

    def _write_report(self, report, path):
        rendered = json.dumps(report, ensure_ascii=False, default=str, sort_keys=True)
        self.stdout.write("GIS_STANDARD_CLEANUP_JSON=" + rendered)
        if path:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(rendered + "\n", encoding="utf-8")
