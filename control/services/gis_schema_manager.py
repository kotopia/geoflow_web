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
