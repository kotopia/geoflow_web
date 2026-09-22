"""GIS-only central definition administration and guarded schema helpers."""
from __future__ import annotations

import json
import re
from uuid import UUID, uuid4

from psycopg2 import sql

from geoflow_ops.gis.form_definitions import DefinitionError


IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
ALLOWED_TYPES = {
    "text", "varchar", "integer", "bigint", "numeric", "double precision",
    "boolean", "date", "timestamp", "timestamptz", "uuid", "jsonb",
}
SCHEMA_OPERATIONS = {"ADD_COLUMN", "RENAME_COLUMN", "DEPRECATE", "DROP_COLUMN", "ALTER_TYPE"}


def _uuid(value, label="식별자"):
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        raise DefinitionError(f"{label}가 올바르지 않습니다.") from None


def identifier(value, label="DB 식별자"):
    value = str(value or "").strip().lower()
    if not IDENTIFIER_RE.fullmatch(value):
        raise DefinitionError(f"{label}는 영문 소문자/숫자/밑줄 형식이어야 합니다.")
    return value


def data_type(value):
    value = " ".join(str(value or "").strip().lower().split())
    if value not in ALLOWED_TYPES:
        raise DefinitionError("허용되지 않은 DB 타입입니다.")
    return value


def _bool(value, default=False):
    if value is None:
        return default
    return value in (True, "true", "on", "1", 1)


def _int(value, default=0):
    try:
        return int(default if value in (None, "") else value)
    except (TypeError, ValueError):
        raise DefinitionError("순서는 정수여야 합니다.") from None


def _label(value):
    value = str(value or "").strip()
    if not value or len(value) > 120:
        raise DefinitionError("표시명 길이를 확인하세요.")
    return value


def _json_list(value, label):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            raise DefinitionError(label + " JSON을 확인하세요.") from None
    if not isinstance(value, list):
        raise DefinitionError(label + "은 목록이어야 합니다.")
    return value


def ensure_admin_schema(cur):
    """Idempotent additive extension for central GIS definition administration."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS gis.definition_layer_group (
          id uuid PRIMARY KEY,
          group_code text NOT NULL UNIQUE CHECK(group_code ~ '^[a-z_][a-z0-9_]*$'),
          group_name text NOT NULL CHECK(length(btrim(group_name)) BETWEEN 1 AND 120),
          display_name text NOT NULL CHECK(length(btrim(display_name)) BETWEEN 1 AND 120),
          sort_order integer NOT NULL DEFAULT 0,
          active boolean NOT NULL DEFAULT true,
          description text NOT NULL DEFAULT '',
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    cur.execute("""
        ALTER TABLE gis.definition_layer
          ADD COLUMN IF NOT EXISTS layer_group_id uuid REFERENCES gis.definition_layer_group(id),
          ADD COLUMN IF NOT EXISTS description text NOT NULL DEFAULT '',
          ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now()
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS definition_layer_layer_group_idx
            ON gis.definition_layer(layer_group_id,sort_order,standard_name)
    """)
    cur.execute("""
        ALTER TABLE gis.definition_field
          ADD COLUMN IF NOT EXISTS active boolean NOT NULL DEFAULT true,
          ADD COLUMN IF NOT EXISTS form_visible boolean,
          ADD COLUMN IF NOT EXISTS table_visible boolean,
          ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now()
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS gis.definition_change_log (
          id uuid PRIMARY KEY,
          actor text NOT NULL DEFAULT '',
          target_type text NOT NULL CHECK(target_type IN ('GROUP','LAYER','FIELD','SCHEMA')),
          target_id uuid,
          change_type text NOT NULL,
          before_value jsonb,
          after_value jsonb,
          schema_applied boolean NOT NULL DEFAULT false,
          created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS definition_change_log_target_idx
            ON gis.definition_change_log(target_type,target_id,created_at DESC)
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS gis.schema_change (
          id uuid PRIMARY KEY,
          operation text NOT NULL CHECK(operation IN
            ('ADD_COLUMN','RENAME_COLUMN','DEPRECATE','DROP_COLUMN','ALTER_TYPE')),
          layer_id uuid NOT NULL REFERENCES gis.definition_layer(id),
          field_id uuid REFERENCES gis.definition_field(id),
          old_name text,
          new_name text,
          old_type text,
          new_type text,
          status text NOT NULL DEFAULT 'PENDING' CHECK(status IN
            ('PENDING','APPROVED','APPLYING','APPLIED','PARTIAL_APPLIED','PARTIAL_FAILED','FAILED','CANCELLED')),
          preview_sql text NOT NULL DEFAULT '',
          impact jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(impact)='object'),
          created_by text NOT NULL DEFAULT '',
          approved_by text NOT NULL DEFAULT '',
          created_at timestamptz NOT NULL DEFAULT now(),
          approved_at timestamptz
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS gis.schema_change_tenant (
          change_id uuid NOT NULL REFERENCES gis.schema_change(id) ON DELETE CASCADE,
          tenant_group_id uuid NOT NULL,
          status text NOT NULL DEFAULT 'PENDING' CHECK(status IN
            ('PENDING','APPROVED','APPLYING','APPLIED','PARTIAL_APPLIED','PARTIAL_FAILED','FAILED','CANCELLED')),
          error_message text NOT NULL DEFAULT '',
          applied_at timestamptz,
          before_schema jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(before_schema)='object'),
          after_schema jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(after_schema)='object'),
          PRIMARY KEY(change_id,tenant_group_id)
        )
    """)


def admin_schema_ready(cur):
    cur.execute("""
      SELECT to_regclass('gis.definition_layer_group') IS NOT NULL
        AND EXISTS(SELECT 1 FROM information_schema.columns
          WHERE table_schema='gis' AND table_name='definition_layer' AND column_name='layer_group_id')
        AND EXISTS(SELECT 1 FROM information_schema.columns
          WHERE table_schema='gis' AND table_name='definition_field' AND column_name='active')
        AND EXISTS(SELECT 1 FROM information_schema.columns
          WHERE table_schema='gis' AND table_name='definition_field' AND column_name='form_visible')
        AND EXISTS(SELECT 1 FROM information_schema.columns
          WHERE table_schema='gis' AND table_name='definition_field' AND column_name='table_visible')
        AND to_regclass('gis.definition_change_log') IS NOT NULL
        AND to_regclass('gis.schema_change') IS NOT NULL
        AND to_regclass('gis.schema_change_tenant') IS NOT NULL
    """)
    return bool(cur.fetchone()[0])


def actor_name(request):
    user = getattr(request, "user", None)
    return str(getattr(user, "email", None) or getattr(user, "username", None)
               or getattr(user, "pk", None) or "")[:240]


def audit(cur, *, actor="", target_type, target_id=None, change_type,
          before=None, after=None, schema_applied=False):
    cur.execute(
        """INSERT INTO gis.definition_change_log
           (id,actor,target_type,target_id,change_type,before_value,after_value,schema_applied)
           VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s)""",
        [
            str(uuid4()), str(actor or "")[:240], target_type,
            _uuid(target_id) if target_id else None, str(change_type)[:120],
            json.dumps(before, ensure_ascii=False, default=str) if before is not None else None,
            json.dumps(after, ensure_ascii=False, default=str) if after is not None else None,
            bool(schema_applied),
        ],
    )


def _row(cur, query, params):
    cur.execute(query, params)
    columns = [item[0] for item in cur.description]
    value = cur.fetchone()
    return dict(zip(columns, value)) if value else None


def layer_group_state(cur, group_id):
    return _row(cur, """SELECT id::text,group_code,group_name,display_name,sort_order,active,description
        FROM gis.definition_layer_group WHERE id=%s""", [_uuid(group_id)])


def business_group_state(cur, group_id):
    return _row(cur, "SELECT id::text,name FROM gis.definition_group WHERE id=%s", [_uuid(group_id)])


def layer_state(cur, layer_id):
    return _row(cur, """SELECT id::text,standard_name,physical_name,label,domain_code,geometry_kind,
        feature_role,scope_type,sort_order,active,layer_group_id::text,description
        FROM gis.definition_layer WHERE id=%s""", [_uuid(layer_id)])


def field_state(cur, field_id):
    return _row(cur, """SELECT id::text,source_layer_id::text,physical_name,standard_name,label,
        storage_data_type,storage_udt_name,kind,widget_type,visible,form_visible,
        table_visible,required,readonly,sort_order,unit,description,active
        FROM gis.definition_field WHERE id=%s""", [_uuid(field_id)])


def effective_form_visible(field):
    return bool(field.get("visible", True) if field.get("form_visible") is None else field["form_visible"])


def effective_table_visible(field):
    return bool(field.get("visible", True) if field.get("table_visible") is None else field["table_visible"])


def rollout_status(registered, tenant_status, targets, succeeded):
    registered=list(registered)
    targets=list(targets)
    succeeded=list(succeeded)
    all_registered_applied=bool(registered) and all(
        tenant_status.get(group_id)=="APPLIED" for group_id in registered
    )
    requested_ok=len(succeeded)==len(targets)
    if all_registered_applied:
        return "APPLIED", True
    if requested_ok:
        return "PARTIAL_APPLIED", False
    if succeeded:
        return "PARTIAL_FAILED", False
    return "FAILED", False


def impact_for_group(cur, group_id):
    group_id = _uuid(group_id)
    cur.execute("SELECT count(*) FROM gis.definition_layer WHERE layer_group_id=%s", [group_id])
    return {"group_layers": int(cur.fetchone()[0]), "group_fields": 0}


def impact_for_field(cur, field_id):
    field_id = _uuid(field_id)
    counts = {}
    queries = {
        "field_layers": "SELECT count(*) FROM gis.definition_field_layer WHERE field_id=%s",
        "group_fields": "SELECT count(*) FROM gis.definition_group_field WHERE field_id=%s",
        "codes": "SELECT count(*) FROM gis.definition_code WHERE field_id=%s",
        "rules_source": "SELECT count(*) FROM gis.definition_rule WHERE source_field=%s",
        "rules_target": "SELECT count(*) FROM gis.definition_rule WHERE target_field=%s",
    }
    for key, query in queries.items():
        cur.execute(query, [field_id])
        counts[key] = int(cur.fetchone()[0])
    return counts


def _layer_physical(cur, layer_id):
    row = _row(cur, "SELECT id::text,physical_name,standard_name FROM gis.definition_layer WHERE id=%s",
               [_uuid(layer_id)])
    if not row:
        raise DefinitionError("레이어를 찾을 수 없습니다.")
    row["physical_name"] = identifier(row["physical_name"], "레이어 테이블명")
    return row


def preview_sql(*, operation, table_name, old_name=None, new_name=None, new_type=None):
    table_name = identifier(table_name, "레이어 테이블명")
    if operation == "ADD_COLUMN":
        return f'ALTER TABLE gis."{table_name}" ADD COLUMN "{identifier(new_name, "신규 컬럼명")}" {data_type(new_type)};'
    if operation == "RENAME_COLUMN":
        return f'ALTER TABLE gis."{table_name}" RENAME COLUMN "{identifier(old_name, "기존 컬럼명")}" TO "{identifier(new_name, "신규 컬럼명")}";'
    if operation == "DROP_COLUMN":
        return f'ALTER TABLE gis."{table_name}" DROP COLUMN "{identifier(old_name, "컬럼명")}";'
    if operation == "ALTER_TYPE":
        return f'ALTER TABLE gis."{table_name}" ALTER COLUMN "{identifier(old_name, "컬럼명")}" TYPE {data_type(new_type)};'
    if operation == "DEPRECATE":
        return "-- Definition-only deprecation; no physical DDL."
    raise DefinitionError("지원하지 않는 Schema 변경입니다.")


def create_schema_change(cur, data, *, actor=""):
    operation = str(data.get("operation") or "").strip().upper()
    if operation not in SCHEMA_OPERATIONS:
        raise DefinitionError("지원하지 않는 Schema 변경입니다.")
    layer = _layer_physical(cur, data.get("layer_id"))
    field_id = _uuid(data.get("field_id"), "필드") if data.get("field_id") else None
    old_name = identifier(data.get("old_name"), "기존 컬럼명") if data.get("old_name") else None
    new_name = identifier(data.get("new_name"), "신규 컬럼명") if data.get("new_name") else None
    old_type = data_type(data.get("old_type")) if data.get("old_type") else None
    new_type = data_type(data.get("new_type")) if data.get("new_type") else None
    if operation == "ADD_COLUMN" and (not new_name or not new_type):
        raise DefinitionError("ADD COLUMN에는 컬럼명과 타입이 필요합니다.")
    if operation == "RENAME_COLUMN" and (not old_name or not new_name):
        raise DefinitionError("RENAME COLUMN에는 기존/신규 컬럼명이 필요합니다.")
    if operation == "DROP_COLUMN" and not old_name:
        raise DefinitionError("DROP COLUMN에는 컬럼명이 필요합니다.")
    if operation == "ALTER_TYPE" and (not old_name or not new_type):
        raise DefinitionError("TYPE 변경에는 컬럼명과 신규 타입이 필요합니다.")
    preview = preview_sql(operation=operation, table_name=layer["physical_name"],
                          old_name=old_name, new_name=new_name, new_type=new_type)
    impact = {"central_references": impact_for_field(cur, field_id) if field_id else {},
              "tenant_check_required": True}
    change_id = str(uuid4())
    cur.execute(
        """INSERT INTO gis.schema_change
           (id,operation,layer_id,field_id,old_name,new_name,old_type,new_type,status,
            preview_sql,impact,created_by)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'PENDING',%s,%s::jsonb,%s)""",
        [change_id, operation, layer["id"], field_id, old_name, new_name, old_type, new_type,
         preview, json.dumps(impact, ensure_ascii=False), str(actor or "")[:240]],
    )
    audit(cur, actor=actor, target_type="SCHEMA", target_id=change_id,
          change_type="CREATE_SCHEMA_CHANGE",
          after={"operation": operation, "layer_id": layer["id"], "preview_sql": preview, "impact": impact})
    return change_id


def tenant_column_state(cur, *, table_name, column_name=None):
    table_name = identifier(table_name, "레이어 테이블명")
    cur.execute("SELECT to_regclass(%s)", [f"gis.{table_name}"])
    if cur.fetchone()[0] is None:
        return {"table_exists": False, "column": None, "non_null_rows": 0}
    if not column_name:
        return {"table_exists": True, "column": None, "non_null_rows": 0}
    column_name = identifier(column_name, "컬럼명")
    cur.execute(
        """SELECT data_type,udt_name,is_nullable,character_maximum_length,
                  numeric_precision,numeric_scale
             FROM information_schema.columns
            WHERE table_schema='gis' AND table_name=%s AND column_name=%s""",
        [table_name, column_name],
    )
    row = cur.fetchone()
    if not row:
        return {"table_exists": True, "column": None, "non_null_rows": 0}
    keys = ("data_type", "udt_name", "is_nullable", "max_length", "precision", "scale")
    state = dict(zip(keys, row))
    cur.execute(sql.SQL("SELECT count(*) FROM {}.{} WHERE {} IS NOT NULL").format(
        sql.Identifier("gis"), sql.Identifier(table_name), sql.Identifier(column_name)))
    return {"table_exists": True, "column": state, "non_null_rows": int(cur.fetchone()[0])}


def apply_change_to_tenant(cur, change):
    operation = change.get("operation")
    if operation not in SCHEMA_OPERATIONS:
        raise DefinitionError("지원하지 않는 Schema 변경입니다.")
    table_name = identifier(change["table_name"], "레이어 테이블명")
    if operation == "DEPRECATE":
        return
    if operation == "ADD_COLUMN":
        stmt = sql.SQL("ALTER TABLE {}.{} ADD COLUMN {} {}").format(
            sql.Identifier("gis"), sql.Identifier(table_name),
            sql.Identifier(identifier(change["new_name"], "신규 컬럼명")),
            sql.SQL(data_type(change["new_type"])))
    elif operation == "RENAME_COLUMN":
        stmt = sql.SQL("ALTER TABLE {}.{} RENAME COLUMN {} TO {}").format(
            sql.Identifier("gis"), sql.Identifier(table_name),
            sql.Identifier(identifier(change["old_name"], "기존 컬럼명")),
            sql.Identifier(identifier(change["new_name"], "신규 컬럼명")))
    elif operation == "DROP_COLUMN":
        stmt = sql.SQL("ALTER TABLE {}.{} DROP COLUMN {}").format(
            sql.Identifier("gis"), sql.Identifier(table_name),
            sql.Identifier(identifier(change["old_name"], "컬럼명")))
    elif operation == "ALTER_TYPE":
        stmt = sql.SQL("ALTER TABLE {}.{} ALTER COLUMN {} TYPE {}").format(
            sql.Identifier("gis"), sql.Identifier(table_name),
            sql.Identifier(identifier(change["old_name"], "컬럼명")),
            sql.SQL(data_type(change["new_type"])))
    cur.execute(stmt)


def schema_change_snapshot(cur):
    cur.execute(
        """SELECT sc.id::text,sc.operation,sc.layer_id::text,l.standard_name,l.physical_name,
                  sc.field_id::text,sc.old_name,sc.new_name,sc.old_type,sc.new_type,
                  sc.status,sc.preview_sql,sc.impact,sc.created_by,sc.approved_by,
                  sc.created_at,sc.approved_at
             FROM gis.schema_change sc JOIN gis.definition_layer l ON l.id=sc.layer_id
            ORDER BY sc.created_at DESC,sc.id DESC"""
    )
    columns = [item[0] for item in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def change_log_snapshot(cur, limit=200):
    cur.execute(
        """SELECT id::text,actor,target_type,target_id::text,change_type,before_value,
                  after_value,schema_applied,created_at
             FROM gis.definition_change_log
            ORDER BY created_at DESC,id DESC LIMIT %s""",
        [max(1, min(int(limit), 1000))],
    )
    columns = [item[0] for item in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def mutate_admin(cur, data, *, actor=""):
    action = str(data.get("action") or "")
    if action == "group_admin":
        uid = _uuid(data.get("id")) if data.get("id") else str(uuid4())
        before = layer_group_state(cur, uid) if data.get("id") else None
        code = identifier(data.get("group_code") or ("group_" + uid.replace("-", "")), "그룹 코드")
        name = _label(data.get("name") or data.get("label"))
        display = _label(data.get("display_name") or name)
        cur.execute(
            """INSERT INTO gis.definition_layer_group
               (id,group_code,group_name,display_name,sort_order,active,description,updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,now())
               ON CONFLICT(id) DO UPDATE SET group_code=EXCLUDED.group_code,
                 group_name=EXCLUDED.group_name,display_name=EXCLUDED.display_name,
                 sort_order=EXCLUDED.sort_order,active=EXCLUDED.active,
                 description=EXCLUDED.description,updated_at=now()""",
            [uid, code, name, display, _int(data.get("sort_order")),
             _bool(data.get("active"), True), str(data.get("description") or "")[:2000]],
        )
        audit(cur, actor=actor, target_type="GROUP", target_id=uid,
              change_type="UPDATE" if before else "CREATE", before=before, after=layer_group_state(cur, uid))
        return uid

    if action == "delete_group_admin":
        uid = _uuid(data.get("id"), "그룹")
        before = layer_group_state(cur, uid)
        if not before:
            raise DefinitionError("레이어 그룹을 찾을 수 없습니다.")
        impact = impact_for_group(cur, uid)
        if impact["group_layers"]:
            raise DefinitionError(f"이 그룹에는 {impact['group_layers']}개의 레이어가 있습니다. 다른 그룹 또는 미분류로 이동한 후 삭제하세요.")
        cur.execute("DELETE FROM gis.definition_layer_group WHERE id=%s", [uid])
        audit(cur, actor=actor, target_type="GROUP", target_id=uid,
              change_type="DELETE_EMPTY_GROUP", before=before, after=None)
        return uid

    if action == "layer_admin":
        uid = _uuid(data.get("id")) if data.get("id") else str(uuid4())
        before = layer_state(cur, uid) if data.get("id") else None
        if before:
            standard_name, physical_name = before["standard_name"], before["physical_name"]
        else:
            standard_name = str(data.get("standard_name") or "").strip().upper()
            if not standard_name or len(standard_name) > 120:
                raise DefinitionError("표준 레이어명을 확인하세요.")
            physical_name = identifier(data.get("physical_name"), "물리 테이블명")
        geometry = str(data.get("geometry_kind") or (before or {}).get("geometry_kind") or "").upper()
        if geometry not in ("", "POINT", "LINE", "POLYGON"):
            raise DefinitionError("Geometry 유형을 확인하세요.")
        layer_group_id = data.get("layer_group_id") if "layer_group_id" in data else (before or {}).get("layer_group_id")
        if layer_group_id:
            layer_group_id = _uuid(layer_group_id, "레이어 그룹")
            if not layer_group_state(cur, layer_group_id):
                raise DefinitionError("레이어 그룹을 찾을 수 없습니다.")
        cur.execute(
            """INSERT INTO gis.definition_layer
               (id,standard_name,physical_name,label,domain_code,geometry_kind,feature_role,
                scope_type,sort_order,active,layer_group_id,description,updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
               ON CONFLICT(id) DO UPDATE SET label=EXCLUDED.label,domain_code=EXCLUDED.domain_code,
                 geometry_kind=EXCLUDED.geometry_kind,feature_role=EXCLUDED.feature_role,
                 scope_type=EXCLUDED.scope_type,sort_order=EXCLUDED.sort_order,
                 active=EXCLUDED.active,layer_group_id=EXCLUDED.layer_group_id,
                 description=EXCLUDED.description,updated_at=now()""",
            [uid, standard_name, physical_name, _label(data.get("label")),
             str(data.get("domain_code") or "")[:40], geometry,
             str(data.get("feature_role") or (before or {}).get("feature_role") or "ASSET")[:40],
             str(data.get("scope_type") or (before or {}).get("scope_type") or "PROJECT")[:40],
             _int(data.get("sort_order")), _bool(data.get("active"), bool(before and before["active"])),
             layer_group_id, str(data.get("description") or "")[:2000]],
        )
        audit(cur, actor=actor, target_type="LAYER", target_id=uid,
              change_type="UPDATE" if before else "CREATE", before=before, after=layer_state(cur, uid))
        return uid

    if action == "deactivate_layer_admin":
        uid = _uuid(data.get("id"), "레이어")
        before = layer_state(cur, uid)
        if not before:
            raise DefinitionError("레이어를 찾을 수 없습니다.")
        cur.execute("UPDATE gis.definition_layer SET active=false,updated_at=now() WHERE id=%s", [uid])
        audit(cur, actor=actor, target_type="LAYER", target_id=uid,
              change_type="DEACTIVATE", before=before, after=layer_state(cur, uid))
        return uid

    if action == "field_admin":
        uid = _uuid(data.get("id")) if data.get("id") else str(uuid4())
        before = field_state(cur, uid) if data.get("id") else None
        kind = str(data.get("kind") or (before or {}).get("kind") or "text")
        if kind not in {"text","integer","decimal","boolean","date","datetime","photo","relation"}:
            raise DefinitionError("필드 유형을 확인하세요.")
        widget = str(data.get("widget_type") or (before or {}).get("widget_type") or "text")
        if widget not in {"text","multiline","integer","decimal","combo","boolean","date","datetime","photo","relation","hidden"}:
            raise DefinitionError("Widget 유형을 확인하세요.")
        if before:
            source_layer_id, physical_name = before["source_layer_id"], before["physical_name"]
            standard_name, storage_data_type = before["standard_name"], before["storage_data_type"]
        else:
            source_layer_id = _uuid(data.get("source_layer_id"), "레이어") if data.get("source_layer_id") else None
            physical_name = identifier(data.get("physical_name"), "DB 필드명") if source_layer_id else None
            standard_name = str(data.get("standard_name") or physical_name or "").strip().upper() or None
            storage_data_type = data_type(data.get("storage_data_type")) if source_layer_id else None
            if source_layer_id and not layer_state(cur, source_layer_id):
                raise DefinitionError("레이어를 찾을 수 없습니다.")
        visible = _bool(data.get("visible"), bool((before or {}).get("visible", True)))
        form_visible = _bool(data.get("form_visible"), visible)
        table_visible = _bool(data.get("table_visible"), visible)
        active_default = bool((before or {}).get("active", False if not before and source_layer_id else True))
        cur.execute(
            """INSERT INTO gis.definition_field
               (id,source_layer_id,physical_name,standard_name,label,storage_data_type,kind,widget_type,
                visible,form_visible,table_visible,required,readonly,sort_order,unit,description,active,layout,updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'{}'::jsonb,now())
               ON CONFLICT(id) DO UPDATE SET label=EXCLUDED.label,kind=EXCLUDED.kind,
                 widget_type=EXCLUDED.widget_type,visible=EXCLUDED.visible,
                 form_visible=EXCLUDED.form_visible,table_visible=EXCLUDED.table_visible,
                 required=EXCLUDED.required,readonly=EXCLUDED.readonly,sort_order=EXCLUDED.sort_order,
                 unit=EXCLUDED.unit,description=EXCLUDED.description,active=EXCLUDED.active,updated_at=now()""",
            [uid, source_layer_id, physical_name, standard_name, _label(data.get("label")),
             storage_data_type, kind, widget, visible, form_visible, table_visible,
             _bool(data.get("required")), _bool(data.get("readonly")), _int(data.get("sort_order")),
             str(data.get("unit") or "")[:40], str(data.get("description") or "")[:2000],
             _bool(data.get("active"), active_default)],
        )
        if source_layer_id:
            cur.execute("""INSERT INTO gis.definition_field_layer(field_id,layer_id)
                           VALUES (%s,%s) ON CONFLICT DO NOTHING""", [uid, source_layer_id])
        audit(cur, actor=actor, target_type="FIELD", target_id=uid,
              change_type="UPDATE" if before else ("CREATE_PENDING_SCHEMA" if source_layer_id else "CREATE"),
              before=before, after=field_state(cur, uid))
        return uid

    if action == "deactivate_field_admin":
        uid = _uuid(data.get("id"), "필드")
        before = field_state(cur, uid)
        if not before:
            raise DefinitionError("필드를 찾을 수 없습니다.")
        cur.execute("UPDATE gis.definition_field SET active=false,updated_at=now() WHERE id=%s", [uid])
        audit(cur, actor=actor, target_type="FIELD", target_id=uid,
              change_type="DEACTIVATE", before=before, after=field_state(cur, uid))
        return uid

    if action == "bulk_fields_admin":
        items = _json_list(data.get("items"), "필드 일괄 편집")
        if len(items) > 500:
            raise DefinitionError("한 번에 500개 필드까지만 수정할 수 있습니다.")
        for item in items:
            if not isinstance(item, dict) or not item.get("id"):
                raise DefinitionError("필드 일괄 편집 항목을 확인하세요.")
            current = field_state(cur, item["id"])
            if not current:
                raise DefinitionError("필드를 찾을 수 없습니다.")
            mutate_admin(cur, {**current, **item, "action": "field_admin"}, actor=actor)
        return ""

    if action == "bulk_layers_admin":
        items = _json_list(data.get("items"), "레이어 일괄 편집")
        if len(items) > 300:
            raise DefinitionError("한 번에 300개 레이어까지만 수정할 수 있습니다.")
        for item in items:
            if not isinstance(item, dict) or not item.get("id"):
                raise DefinitionError("레이어 일괄 편집 항목을 확인하세요.")
            current = layer_state(cur, item["id"])
            if not current:
                raise DefinitionError("레이어를 찾을 수 없습니다.")
            mutate_admin(cur, {**current, **item, "action": "layer_admin",
                               "layer_group_id": item.get("layer_group_id", current.get("layer_group_id")),
                               "label": item.get("label", current["label"])}, actor=actor)
        return ""

    if action == "schema_change_admin":
        return create_schema_change(cur, data, actor=actor)

    raise DefinitionError("지원하지 않는 GIS 관리 요청입니다.")
