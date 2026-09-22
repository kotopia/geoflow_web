"""Execution boundary for approved GIS schema changes.

No arbitrary SQL is accepted. Every physical mutation is limited to the tenant
gis schema and uses validated identifiers from gis_schema_manager.
"""
from __future__ import annotations

import json
from uuid import UUID

from django.db import connections, transaction

from control.models import GroupDBConfig
from control.services.gis_admin import tenant_cursor
from control.services import gis_schema_manager as manager
from geoflow_ops.gis.form_definitions import DefinitionError


def _uuid(value):
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        raise DefinitionError("Schema 변경 식별자가 올바르지 않습니다.") from None


def registered_tenant_ids():
    return [
        str(value)
        for value in GroupDBConfig.objects.using("default")
        .filter(group__status="active")
        .exclude(db_alias="default")
        .order_by("group_id")
        .values_list("group_id", flat=True)
    ]


def get_change(change_id, *, lock=False):
    query = """SELECT sc.id::text,sc.operation,sc.layer_id::text,l.physical_name AS table_name,
                      sc.field_id::text,sc.old_name,sc.new_name,sc.old_type,sc.new_type,
                      sc.status,sc.preview_sql,sc.impact
                 FROM gis.schema_change sc JOIN gis.definition_layer l ON l.id=sc.layer_id
                WHERE sc.id=%s"""
    if lock:
        query += " FOR UPDATE"
    with connections["default"].cursor() as cur:
        cur.execute(query, [_uuid(change_id)])
        row = cur.fetchone()
        if not row:
            raise DefinitionError("Schema 변경 요청을 찾을 수 없습니다.")
        keys = [item[0] for item in cur.description]
        return dict(zip(keys, row))


def inspect_tenant(change, group_id):
    column_name = change.get("old_name") or change.get("new_name")
    with tenant_cursor(group_id, write=False) as cur:
        state = manager.tenant_column_state(
            cur, table_name=change["table_name"], column_name=column_name
        )
        state["project_definition_refs"] = 0
        state["attachment_refs"] = 0
        field_id = change.get("field_id")
        if field_id:
            cur.execute("SELECT to_regclass('gis.project_definition')")
            if cur.fetchone()[0]:
                cur.execute(
                    """SELECT count(*) FROM gis.project_definition
                        WHERE additions ? %s OR private_items ? %s OR overrides ? %s""",
                    [field_id, field_id, field_id],
                )
                state["project_definition_refs"] = int(cur.fetchone()[0])
            cur.execute("SELECT to_regclass('ops.attachments')")
            if cur.fetchone()[0]:
                cur.execute(
                    "SELECT count(*) FROM ops.attachments WHERE purpose=%s",
                    ["gis_form:" + field_id],
                )
                state["attachment_refs"] = int(cur.fetchone()[0])
        return state


def inspect_all(change):
    result = {}
    for group_id in registered_tenant_ids():
        try:
            result[group_id] = {"ok": True, **inspect_tenant(change, group_id)}
        except Exception as exc:
            result[group_id] = {
                "ok": False,
                "error": type(exc).__name__,
                "table_exists": None,
                "column": None,
                "non_null_rows": None,
            }
    return result


def approve(change_id, *, actor="", allow_data_loss=False):
    impacts = inspect_all(get_change(change_id))
    unreachable = [gid for gid, value in impacts.items() if not value.get("ok")]
    if unreachable:
        raise DefinitionError("영향을 확인할 수 없는 테넌트가 있어 승인을 중지했습니다.")
    change = get_change(change_id)
    if change["operation"] == "DROP_COLUMN":
        affected = sum(int(value.get("non_null_rows") or 0) for value in impacts.values())
        if affected and not allow_data_loss:
            raise DefinitionError(
                f"삭제 대상 컬럼에 값이 있는 행이 {affected}건 있습니다. 데이터 삭제 확인이 필요합니다."
            )
    with transaction.atomic(using="default"):
        with connections["default"].cursor() as cur:
            cur.execute("SELECT status FROM gis.schema_change WHERE id=%s FOR UPDATE", [_uuid(change_id)])
            row = cur.fetchone()
            if not row:
                raise DefinitionError("Schema 변경 요청을 찾을 수 없습니다.")
            if row[0] not in ("PENDING", "FAILED", "PARTIAL_FAILED"):
                raise DefinitionError("현재 상태에서는 승인할 수 없습니다.")
            cur.execute(
                """UPDATE gis.schema_change
                      SET status='APPROVED',approved_by=%s,approved_at=now(),impact=%s::jsonb
                    WHERE id=%s""",
                [str(actor or "")[:240], json.dumps({"tenants": impacts}, ensure_ascii=False, default=str),
                 _uuid(change_id)],
            )
            manager.audit(
                cur, actor=actor, target_type="SCHEMA", target_id=change_id,
                change_type="APPROVE_SCHEMA_CHANGE",
                after={"tenant_count": len(impacts), "allow_data_loss": bool(allow_data_loss)},
            )
    return impacts


def _record_target(change_id, group_id, *, status, error="", before=None, after=None):
    with transaction.atomic(using="default"):
        with connections["default"].cursor() as cur:
            cur.execute(
                """INSERT INTO gis.schema_change_tenant
                   (change_id,tenant_group_id,status,error_message,applied_at,before_schema,after_schema)
                   VALUES (%s,%s,%s,%s,CASE WHEN %s='APPLIED' THEN now() ELSE NULL END,
                           %s::jsonb,%s::jsonb)
                   ON CONFLICT(change_id,tenant_group_id) DO UPDATE SET
                     status=EXCLUDED.status,error_message=EXCLUDED.error_message,
                     applied_at=EXCLUDED.applied_at,before_schema=EXCLUDED.before_schema,
                     after_schema=EXCLUDED.after_schema""",
                [
                    _uuid(change_id), str(group_id), status, str(error or "")[:2000], status,
                    json.dumps(before or {}, ensure_ascii=False, default=str),
                    json.dumps(after or {}, ensure_ascii=False, default=str),
                ],
            )


def _finalize(change, targets, succeeded, *, actor=""):
    requested_ok = len(succeeded) == len(targets)
    registered = registered_tenant_ids()
    with connections["default"].cursor() as status_cursor:
        status_cursor.execute(
            "SELECT tenant_group_id::text,status FROM gis.schema_change_tenant WHERE change_id=%s",
            [change["id"]],
        )
        tenant_status = dict(status_cursor.fetchall())
    status, all_registered_applied = manager.rollout_status(
        registered, tenant_status, targets, succeeded
    )
    with transaction.atomic(using="default"):
        with connections["default"].cursor() as cur:
            cur.execute("UPDATE gis.schema_change SET status=%s WHERE id=%s", [status, change["id"]])
            if all_registered_applied:
                if change["operation"] == "ADD_COLUMN" and change.get("field_id"):
                    before = manager.field_state(cur, change["field_id"])
                    cur.execute(
                        "UPDATE gis.definition_field SET active=true,updated_at=now() WHERE id=%s",
                        [change["field_id"]],
                    )
                    manager.audit(
                        cur, actor=actor, target_type="FIELD", target_id=change["field_id"],
                        change_type="SCHEMA_ADD_APPLIED", before=before,
                        after=manager.field_state(cur, change["field_id"]), schema_applied=True,
                    )
                elif change["operation"] == "RENAME_COLUMN" and change.get("field_id"):
                    before = manager.field_state(cur, change["field_id"])
                    cur.execute(
                        """UPDATE gis.definition_field
                              SET physical_name=%s,updated_at=now()
                            WHERE id=%s""",
                        [change["new_name"], change["field_id"]],
                    )
                    manager.audit(
                        cur, actor=actor, target_type="FIELD", target_id=change["field_id"],
                        change_type="SCHEMA_RENAME_APPLIED", before=before,
                        after=manager.field_state(cur, change["field_id"]), schema_applied=True,
                    )
                elif change["operation"] == "ALTER_TYPE" and change.get("field_id"):
                    before = manager.field_state(cur, change["field_id"])
                    cur.execute(
                        """UPDATE gis.definition_field
                              SET storage_data_type=%s,updated_at=now()
                            WHERE id=%s""",
                        [change["new_type"], change["field_id"]],
                    )
                    manager.audit(
                        cur, actor=actor, target_type="FIELD", target_id=change["field_id"],
                        change_type="SCHEMA_TYPE_APPLIED", before=before,
                        after=manager.field_state(cur, change["field_id"]), schema_applied=True,
                    )
                elif change["operation"] == "DROP_COLUMN" and change.get("field_id"):
                    before = manager.field_state(cur, change["field_id"])
                    cur.execute(
                        "UPDATE gis.definition_field SET active=false,updated_at=now() WHERE id=%s",
                        [change["field_id"]],
                    )
                    manager.audit(
                        cur, actor=actor, target_type="FIELD", target_id=change["field_id"],
                        change_type="SCHEMA_DROP_APPLIED", before=before,
                        after=manager.field_state(cur, change["field_id"]), schema_applied=True,
                    )
            manager.audit(
                cur, actor=actor, target_type="SCHEMA", target_id=change["id"],
                change_type="APPLY_SCHEMA_CHANGE",
                after={"status": status, "targets": targets, "succeeded": succeeded,
                       "all_registered_applied": all_registered_applied},
                schema_applied=all_registered_applied,
            )
    return status


def apply(change_id, tenant_group_ids, *, actor="", confirmation=""):
    change = get_change(change_id)
    if change["status"] not in ("APPROVED", "PARTIAL_APPLIED", "APPLIED", "FAILED", "PARTIAL_FAILED"):
        raise DefinitionError("승인된 Schema 변경만 적용할 수 있습니다.")

    registered = registered_tenant_ids()
    requested = list(dict.fromkeys(_uuid(value) for value in tenant_group_ids))
    if not requested:
        raise DefinitionError("적용할 테넌트를 선택하세요.")
    if not set(requested) <= set(registered):
        raise DefinitionError("등록되지 않은 테넌트가 포함되어 있습니다.")

    if change["operation"] in ("RENAME_COLUMN", "DROP_COLUMN", "ALTER_TYPE"):
        if set(requested) != set(registered):
            raise DefinitionError(
                "RENAME/DROP/TYPE 변경은 중앙 Definition 불일치를 막기 위해 등록 tenant 전체 적용이 필요합니다."
            )

    if change["operation"] == "DROP_COLUMN":
        if change.get("field_id"):
            with connections["default"].cursor() as cur:
                field = manager.field_state(cur, change["field_id"])
            if field and field.get("active"):
                raise DefinitionError("DB 컬럼 영구 삭제 전에 필드를 먼저 비활성화하세요.")
        expected = "DROP COLUMN " + str(change.get("old_name") or "")
        if confirmation != expected:
            raise DefinitionError(f"영구 삭제 확인 문구가 필요합니다: {expected}")

    with connections["default"].cursor() as status_cursor:
        status_cursor.execute(
            "SELECT tenant_group_id::text,status FROM gis.schema_change_tenant WHERE change_id=%s",
            [_uuid(change_id)],
        )
        previous_status = dict(status_cursor.fetchall())
    succeeded = [group_id for group_id in requested if previous_status.get(group_id) == "APPLIED"]
    for group_id in requested:
        if group_id in succeeded:
            continue
        before = {}
        try:
            with tenant_cursor(group_id, write=True) as cur:
                before = manager.tenant_column_state(
                    cur,
                    table_name=change["table_name"],
                    column_name=change.get("old_name") or change.get("new_name"),
                )
                if not before.get("table_exists"):
                    raise DefinitionError("대상 GIS 테이블이 없습니다.")
                already_applied = manager.change_already_applied(cur, change)
                if not already_applied:
                    if change["operation"] in ("RENAME_COLUMN", "DROP_COLUMN", "ALTER_TYPE") and not before.get("column"):
                        raise DefinitionError("대상 GIS 컬럼이 없습니다.")
                    manager.apply_change_to_tenant(cur, change)
                after = manager.tenant_column_state(
                    cur,
                    table_name=change["table_name"],
                    column_name=change.get("new_name") if change["operation"] in ("ADD_COLUMN","RENAME_COLUMN")
                    else change.get("old_name"),
                )
            _record_target(change_id, group_id, status="APPLIED", before=before, after=after)
            succeeded.append(group_id)
        except Exception as exc:
            message=f"{type(exc).__name__}: {str(exc)}".strip()
            _record_target(
                change_id, group_id, status="FAILED", error=message, before=before, after={}
            )

    status = _finalize(change, requested, succeeded, actor=actor)
    return {"status": status, "targets": requested, "succeeded": succeeded}
