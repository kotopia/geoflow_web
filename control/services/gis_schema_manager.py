"""Restricted GIS definition administration and tenant schema-change helpers.

This module is deliberately scoped to central GIS definition metadata and the
tenant gis schema. It never accepts arbitrary SQL from a request.
"""
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
SCHEMA_OPERATIONS = {
    "ADD_COLUMN", "RENAME_COLUMN", "DEPRECATE", "DROP_COLUMN", "ALTER_TYPE",
}
SCHEMA_STATUSES = {
    "PENDING", "APPROVED", "APPLYING", "APPLIED",
    "PARTIAL_FAILED", "FAILED", "CANCELLED",
}


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


def ensure_admin_schema(cur):
    """Idempotently add only central GIS-definition administration structures."""
    cur.execute("""
        ALTER TABLE gis.definition_group
          ADD COLUMN IF NOT EXISTS group_code text,
          ADD COLUMN IF NOT EXISTS display_name text,
          ADD COLUMN IF NOT EXISTS sort_order integer NOT NULL DEFAULT 0,
          ADD COLUMN IF NOT EXISTS active boolean NOT NULL DEFAULT true,
          ADD COLUMN IF NOT EXISTS description text NOT NULL DEFAULT '',
          ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now(),
          ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now()
    """)
    cur.execute("""
        UPDATE gis.definition_group
           SET group_code = COALESCE(NULLIF(group_code,''), 'group_' || replace(id::text,'-','')),
               display_name = COALESCE(NULLIF(display_name,''), name)
         WHERE group_code IS NULL OR group_code='' OR display_name IS NULL OR display_name=''
    """)
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS definition_group_group_code_uq
            ON gis.definition_group(group_code)
    """)
    cur.execute("""
        ALTER TABLE gis.definition_layer
          ADD COLUMN IF NOT EXISTS description text NOT NULL DEFAULT '',
          ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now()
    """)
    cur.execute("""
        ALTER TABLE gis.definition_group_layer
          ADD COLUMN IF NOT EXISTS sort_order integer NOT NULL DEFAULT 0
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
            ('PENDING','APPROVED','APPLYING','APPLIED','PARTIAL_FAILED','FAILED','CANCELLED')),
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
            ('PENDING','APPROVED','APPLYING','APPLIED','PARTIAL_FAILED','FAILED','CANCELLED')),
          error_message text NOT NULL DEFAULT '',
          applied_at timestamptz,
          before_schema jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(before_schema)='object'),
          after_schema jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(after_schema)='object'),
          PRIMARY KEY(change_id,tenant_group_id)
        )
    """)


def admin_schema_ready(cur):
    cur.execute("""
      SELECT
        EXISTS(SELECT 1 FROM information_schema.columns
          WHERE table_schema='gis' AND table_name='definition_field' AND column_name='active')
        AND EXISTS(SELECT 1 FROM information_schema.columns
          WHERE table_schema='gis' AND table_name='definition_field' AND column_name='form_visible')
        AND to_regclass('gis.definition_change_log') IS NOT NULL
        AND to_regclass('gis.schema_change') IS NOT NULL
        AND to_regclass('gis.schema_change_tenant') IS NOT NULL
    """)
    return bool(cur.fetchone()[0])


def actor_name(request):
    user = getattr(request, "user", None)
    return str(
        getattr(user, "email", None)
        or getattr(user, "username", None)
        or getattr(user, "pk", None)
        or ""
    )[:240]


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


def group_state(cur, group_id):
    return _row(cur, """SELECT id::text,name,group_code,display_name,sort_order,active,description
        FROM gis.definition_group WHERE id=%s""", [_uuid(group_id)])


def layer_state(cur, layer_id):
    return _row(cur, """SELECT id::text,standard_name,physical_name,label,domain_code,geometry_kind,
        feature_role,scope_type,sort_order,active,description
        FROM gis.definition_layer WHERE id=%s""", [_uuid(layer_id)])


def field_state(cur, field_id):
    return _row(cur, """SELECT id::text,source_layer_id::text,physical_name,standard_name,label,
        storage_data_type,storage_udt_name,kind,widget_type,visible,form_visible,
        table_visible,required,readonly,sort_order,unit,description,active
        FROM gis.definition_field WHERE id=%s""", [_uuid(field_id)])


def effective_form_visible(field):
    return bool(field.get("visible", True) if field.get("form_visible") is None
                else field["form_visible"])


def effective_table_visible(field):
    return bool(field.get("visible", True) if field.get("table_visible") is None
                else field["table_visible"])


def impact_for_group(cur, group_id):
    group_id = _uuid(group_id)
    cur.execute("SELECT count(*) FROM gis.definition_group_layer WHERE group_id=%s", [group_id])
    layer_count = int(cur.fetchone()[0])
    cur.execute("SELECT count(*) FROM gis.definition_group_field WHERE group_id=%s", [group_id])
    field_count = int(cur.fetchone()[0])
    return {"group_layers": layer_count, "group_fields": field_count}


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
    row = _row(cur,
        "SELECT id::text,physical_name,standard_name FROM gis.definition_layer WHERE id=%s",
        [_uuid(layer_id)])
    if not row:
        raise DefinitionError("레이어를 찾을 수 없습니다.")
    row["physical_name"] = identifier(row["physical_name"], "레이어 테이블명")
    return row


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
    impact = {
        "central_references": impact_for_field(cur, field_id) if field_id else {},
        "tenant_check_required": True,
    }
    change_id = str(uuid4())
    cur.execute(
        """INSERT INTO gis.schema_change
           (id,operation,layer_id,field_id,old_name,new_name,old_type,new_type,status,
            preview_sql,impact,created_by)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'PENDING',%s,%s::jsonb,%s)""",
        [change_id, operation, layer["id"], field_id, old_name, new_name, old_type,
         new_type, preview, json.dumps(impact, ensure_ascii=False), str(actor or "")[:240]],
    )
    audit(cur, actor=actor, target_type="SCHEMA", target_id=change_id,
          change_type="CREATE_SCHEMA_CHANGE",
          after={"operation": operation, "layer_id": layer["id"],
                 "preview_sql": preview, "impact": impact})
    return change_id


def preview_sql(*, operation, table_name, old_name=None, new_name=None, new_type=None):
    table_name = identifier(table_name, "레이어 테이블명")
    if operation == "ADD_COLUMN":
        new_name = identifier(new_name, "신규 컬럼명")
        new_type = data_type(new_type)
        return f'ALTER TABLE gis."{table_name}" ADD COLUMN "{new_name}" {new_type};'
    if operation == "RENAME_COLUMN":
        old_name = identifier(old_name, "기존 컬럼명")
        new_name = identifier(new_name, "신규 컬럼명")
        return f'ALTER TABLE gis."{table_name}" RENAME COLUMN "{old_name}" TO "{new_name}";'
    if operation == "DROP_COLUMN":
        old_name = identifier(old_name, "컬럼명")
        return f'ALTER TABLE gis."{table_name}" DROP COLUMN "{old_name}";'
    if operation == "ALTER_TYPE":
        old_name = identifier(old_name, "컬럼명")
        new_type = data_type(new_type)
        return f'ALTER TABLE gis."{table_name}" ALTER COLUMN "{old_name}" TYPE {new_type};'
    if operation == "DEPRECATE":
        return "-- Definition-only deprecation; no physical DDL."
    raise DefinitionError("지원하지 않는 Schema 변경입니다.")


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
    statement = sql.SQL("SELECT count(*) FROM {}.{} WHERE {} IS NOT NULL").format(
        sql.Identifier("gis"), sql.Identifier(table_name), sql.Identifier(column_name))
    cur.execute(statement)
    return {"table_exists": True, "column": state, "non_null_rows": int(cur.fetchone()[0])}


def apply_change_to_tenant(cur, change):
    """Apply one prevalidated change to one tenant cursor."""
    if change["operation"] not in SCHEMA_OPERATIONS:
        raise DefinitionError("지원하지 않는 Schema 변경입니다.")
    table_name = identifier(change["table_name"], "레이어 테이블명")

    if change["operation"] == "DEPRECATE":
        return
    if change["operation"] == "ADD_COLUMN":
        statement = sql.SQL("ALTER TABLE {}.{} ADD COLUMN {} {}").format(
            sql.Identifier("gis"), sql.Identifier(table_name),
            sql.Identifier(identifier(change["new_name"], "신규 컬럼명")),
            sql.SQL(data_type(change["new_type"])))
    elif change["operation"] == "RENAME_COLUMN":
        statement = sql.SQL("ALTER TABLE {}.{} RENAME COLUMN {} TO {}").format(
            sql.Identifier("gis"), sql.Identifier(table_name),
            sql.Identifier(identifier(change["old_name"], "기존 컬럼명")),
            sql.Identifier(identifier(change["new_name"], "신규 컬럼명")))
    elif change["operation"] == "DROP_COLUMN":
        statement = sql.SQL("ALTER TABLE {}.{} DROP COLUMN {}").format(
            sql.Identifier("gis"), sql.Identifier(table_name),
            sql.Identifier(identifier(change["old_name"], "컬럼명")))
    elif change["operation"] == "ALTER_TYPE":
        statement = sql.SQL("ALTER TABLE {}.{} ALTER COLUMN {} TYPE {}").format(
            sql.Identifier("gis"), sql.Identifier(table_name),
            sql.Identifier(identifier(change["old_name"], "컬럼명")),
            sql.SQL(data_type(change["new_type"])))
    else:
        raise DefinitionError("지원하지 않는 Schema 변경입니다.")
    cur.execute(statement)


def schema_change_snapshot(cur):
    cur.execute(
        """SELECT sc.id::text,sc.operation,sc.layer_id::text,l.standard_name,l.physical_name,
                  sc.field_id::text,sc.old_name,sc.new_name,sc.old_type,sc.new_type,
                  sc.status,sc.preview_sql,sc.impact,sc.created_by,sc.approved_by,
                  sc.created_at,sc.approved_at
             FROM gis.schema_change sc
             JOIN gis.definition_layer l ON l.id=sc.layer_id
            ORDER BY sc.created_at DESC,sc.id DESC"""
    )
    columns = [item[0] for item in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def change_log_snapshot(cur, limit=200):
    limit = max(1, min(int(limit), 1000))
    cur.execute(
        """SELECT id::text,actor,target_type,target_id::text,change_type,before_value,
                  after_value,schema_applied,created_at
             FROM gis.definition_change_log
            ORDER BY created_at DESC,id DESC LIMIT %s""", [limit])
    columns = [item[0] for item in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


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


def mutate_admin(cur, data, *, actor=""):
    """GIS-only additive CRUD used by the expanded central admin."""
    action = str(data.get("action") or "")
    if action == "group_admin":
        uid = _uuid(data.get("id")) if data.get("id") else str(uuid4())
        before = group_state(cur, uid) if data.get("id") else None
        code = identifier(data.get("group_code") or ("group_" + uid.replace("-", "")), "그룹 코드")
        name = _label(data.get("name") or data.get("label"))
        display = _label(data.get("display_name") or name)
        cur.execute("""INSERT INTO gis.definition_group
            (id,name,group_code,display_name,sort_order,active,description,updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,now())
            ON CONFLICT(id) DO UPDATE SET name=EXCLUDED.name,group_code=EXCLUDED.group_code,
              display_name=EXCLUDED.display_name,sort_order=EXCLUDED.sort_order,
              active=EXCLUDED.active,description=EXCLUDED.description,updated_at=now()""",
            [uid, name, code, display, _int(data.get("sort_order")),
             _bool(data.get("active"), True), str(data.get("description") or "")[:2000]])
        after = group_state(cur, uid)
        audit(cur, actor=actor, target_type="GROUP", target_id=uid,
              change_type="UPDATE" if before else "CREATE", before=before, after=after)
        return uid

    if action == "delete_group_admin":
        uid = _uuid(data.get("id"), "그룹")
        before = group_state(cur, uid)
        if not before:
            raise DefinitionError("그룹을 찾을 수 없습니다.")
        impact = impact_for_group(cur, uid)
        if impact["group_layers"] or impact["group_fields"]:
            raise DefinitionError(
                f"그룹에 레이어 {impact['group_layers']}개/필드 연결 {impact['group_fields']}개가 있어 삭제할 수 없습니다."
            )
        cur.execute("DELETE FROM gis.definition_group_scope WHERE group_id=%s", [uid])
        cur.execute("DELETE FROM gis.definition_group WHERE id=%s", [uid])
        audit(cur, actor=actor, target_type="GROUP", target_id=uid,
              change_type="DELETE_EMPTY_GROUP", before=before, after=None)
        return uid

    if action == "layer_admin":
        uid = _uuid(data.get("id")) if data.get("id") else str(uuid4())
        before = layer_state(cur, uid) if data.get("id") else None
        if before:
            # Physical identity is immutable in ordinary editing.
            standard_name = before["standard_name"]
            physical_name = before["physical_name"]
        else:
            standard_name = str(data.get("standard_name") or "").strip().upper()
            if not standard_name or len(standard_name) > 120:
                raise DefinitionError("표준 레이어명을 확인하세요.")
            physical_name = identifier(data.get("physical_name"), "물리 테이블명")
        geometry = str(data.get("geometry_kind") or (before or {}).get("geometry_kind") or "").upper()
        if geometry not in ("", "POINT", "LINE", "POLYGON"):
            raise DefinitionError("Geometry 유형을 확인하세요.")
        cur.execute("""INSERT INTO gis.definition_layer
            (id,standard_name,physical_name,label,domain_code,geometry_kind,feature_role,
             scope_type,sort_order,active,description,updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
            ON CONFLICT(id) DO UPDATE SET label=EXCLUDED.label,domain_code=EXCLUDED.domain_code,
              geometry_kind=EXCLUDED.geometry_kind,feature_role=EXCLUDED.feature_role,
              scope_type=EXCLUDED.scope_type,sort_order=EXCLUDED.sort_order,
              active=EXCLUDED.active,description=EXCLUDED.description,updated_at=now()""",
            [uid, standard_name, physical_name, _label(data.get("label")),
             str(data.get("domain_code") or "")[:40], geometry,
             str(data.get("feature_role") or (before or {}).get("feature_role") or "ASSET")[:40],
             str(data.get("scope_type") or (before or {}).get("scope_type") or "PROJECT")[:40],
             _int(data.get("sort_order")), _bool(data.get("active"), bool(before and before["active"])),
             str(data.get("description") or "")[:2000]])
        after = layer_state(cur, uid)
        audit(cur, actor=actor, target_type="LAYER", target_id=uid,
              change_type="UPDATE" if before else "CREATE", before=before, after=after)
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

    if action == "group_layer_admin":
        group_id = _uuid(data.get("group_id"), "그룹")
        layer_id = _uuid(data.get("layer_id"), "레이어")
        if not group_state(cur, group_id) or not layer_state(cur, layer_id):
            raise DefinitionError("그룹 또는 레이어를 찾을 수 없습니다.")
        cur.execute("""INSERT INTO gis.definition_group_layer(group_id,layer_id,sort_order)
            VALUES (%s,%s,%s) ON CONFLICT(group_id,layer_id)
            DO UPDATE SET sort_order=EXCLUDED.sort_order""",
            [group_id, layer_id, _int(data.get("sort_order"))])
        audit(cur, actor=actor, target_type="LAYER", target_id=layer_id,
              change_type="GROUP_ASSIGN",
              after={"group_id": group_id, "sort_order": _int(data.get("sort_order"))})
        return layer_id

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
            source_layer_id = before["source_layer_id"]
            physical_name = before["physical_name"]
            standard_name = before["standard_name"]
            storage_data_type = before["storage_data_type"]
        else:
            source_layer_id = _uuid(data.get("source_layer_id"), "레이어") if data.get("source_layer_id") else None
            physical_name = identifier(data.get("physical_name"), "DB 필드명") if source_layer_id else None
            standard_name = str(data.get("standard_name") or (physical_name or "")).strip().upper() or None
            storage_data_type = data_type(data.get("storage_data_type")) if source_layer_id else None
            if source_layer_id and not layer_state(cur, source_layer_id):
                raise DefinitionError("레이어를 찾을 수 없습니다.")
        visible = _bool(data.get("visible"), bool((before or {}).get("visible", True)))
        form_visible = _bool(data.get("form_visible"), visible)
        table_visible = _bool(data.get("table_visible"), visible)
        active = _bool(data.get("active"), bool((before or {}).get("active", False if not before and source_layer_id else True)))
        cur.execute("""INSERT INTO gis.definition_field
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
             str(data.get("unit") or "")[:40], str(data.get("description") or "")[:2000], active])
        if source_layer_id:
            cur.execute("""INSERT INTO gis.definition_field_layer(field_id,layer_id)
                VALUES (%s,%s) ON CONFLICT DO NOTHING""", [uid, source_layer_id])
        after = field_state(cur, uid)
        audit(cur, actor=actor, target_type="FIELD", target_id=uid,
              change_type="UPDATE" if before else "CREATE_PENDING_SCHEMA" if source_layer_id else "CREATE",
              before=before, after=after)
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
            merged = {**current, **item, "action": "field_admin"}
            mutate_admin(cur, merged, actor=actor)
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
            merged = {
                **current,
                **item,
                "action": "layer_admin",
                "label": item.get("label", current["label"]),
            }
            mutate_admin(cur, merged, actor=actor)
            target_group = item.get("group_id") or None
            cur.execute("SELECT group_id::text FROM gis.definition_group_layer WHERE layer_id=%s", [item["id"]])
            current_groups = [row[0] for row in cur.fetchall()]
            if target_group:
                target_group = _uuid(target_group, "그룹")
                mutate_admin(cur, {
                    "action": "group_layer_admin",
                    "group_id": target_group,
                    "layer_id": item["id"],
                    "sort_order": item.get("group_sort_order", item.get("sort_order", 0)),
                }, actor=actor)
                for old_group in current_groups:
                    if old_group == target_group:
                        continue
                    cur.execute("""INSERT INTO gis.definition_group_field
                        (group_id,layer_id,field_id,sort_order,required,visible,readonly,layout)
                        SELECT %s,layer_id,field_id,sort_order,required,visible,readonly,layout
                          FROM gis.definition_group_field
                         WHERE group_id=%s AND layer_id=%s
                        ON CONFLICT(group_id,layer_id,field_id) DO NOTHING""",
                        [target_group, old_group, item["id"]])
                    cur.execute("DELETE FROM gis.definition_group_field WHERE group_id=%s AND layer_id=%s",
                                [old_group, item["id"]])
                    cur.execute("DELETE FROM gis.definition_group_layer WHERE group_id=%s AND layer_id=%s",
                                [old_group, item["id"]])
                    audit(cur, actor=actor, target_type="LAYER", target_id=item["id"],
                          change_type="GROUP_MOVE",
                          before={"group_id": old_group}, after={"group_id": target_group})
            else:
                cur.execute("SELECT count(*) FROM gis.definition_group_field WHERE layer_id=%s", [item["id"]])
                if int(cur.fetchone()[0]):
                    raise DefinitionError("그룹별 필드 설정이 있는 레이어는 미분류로 바로 이동할 수 없습니다.")
                cur.execute("DELETE FROM gis.definition_group_layer WHERE layer_id=%s", [item["id"]])
                if current_groups:
                    audit(cur, actor=actor, target_type="LAYER", target_id=item["id"],
                          change_type="MOVE_UNCLASSIFIED",
                          before={"group_ids": current_groups}, after={"group_id": None})
        return ""

    if action == "schema_change_admin":
        return create_schema_change(cur, data, actor=actor)

    raise DefinitionError("지원하지 않는 GIS 관리 요청입니다.")
