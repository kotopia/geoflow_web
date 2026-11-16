"""Read PostgreSQL catalogs only; never read business rows or execute stored code."""
from __future__ import annotations


def _rows(cursor, sql, parameters=()):
    if parameters:
        cursor.execute(sql, parameters)
    else:
        cursor.execute(sql)
    keys = [column[0] for column in cursor.description]
    return [dict(zip(keys, row)) for row in cursor.fetchall()]


def inspect_definition_storage(cursor):
    """Caller supplies a fresh read-only transaction for one known database.

    Inventory all non-system relation names to discover existing extension
    stores. Detailed columns/constraints are limited to GIS, catalog, and the
    existing project/attachment/settings stores. No credential columns, default
    expressions, view definitions, trigger bodies, or business values are read.
    """
    cursor.execute("SELECT current_database(), current_setting('transaction_read_only'), version()")
    database, read_only, version = cursor.fetchone()
    if read_only != "on":
        raise RuntimeError("Definition inventory requires a read-only transaction")
    relations = _rows(cursor, """
        SELECT n.nspname AS schema_name, c.relname AS relation_name, c.relkind AS kind
          FROM pg_catalog.pg_class c
          JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
         WHERE n.nspname NOT LIKE 'pg\\_%' ESCAPE '\\'
           AND n.nspname <> 'information_schema'
           AND c.relkind IN ('r','p','v','m','f')
         ORDER BY n.nspname,c.relname
    """)
    # Explicit ownership scopes, not user-supplied SQL identifiers.
    scopes = ["gis", "catalog"]
    names = ["ops.attachments", "ops.settings_nodes", "ops.process_events",
             "prj.projects", "prj.scope_item"]
    columns = _rows(cursor, """
        SELECT n.nspname AS schema_name,c.relname AS relation_name,a.attname AS column_name,
               pg_catalog.format_type(a.atttypid,a.atttypmod) AS data_type,
               NOT a.attnotnull AS nullable,a.atthasdef AS has_default,
               a.attidentity AS identity_kind,a.attgenerated AS generated_kind
          FROM pg_catalog.pg_attribute a
          JOIN pg_catalog.pg_class c ON c.oid=a.attrelid
          JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
         WHERE a.attnum>0 AND NOT a.attisdropped AND c.relkind IN ('r','p','v','m','f')
           AND (n.nspname=ANY(%s) OR n.nspname||'.'||c.relname=ANY(%s))
         ORDER BY n.nspname,c.relname,a.attnum
    """, [scopes, names])
    # Constraint types and key columns suffice to discover reuse boundaries.
    # Omit CHECK expressions, which can embed literal business data.
    constraints = _rows(cursor, """
        SELECT n.nspname AS schema_name,c.relname AS relation_name,k.conname AS name,
               k.contype AS kind,k.convalidated AS validated,
               ARRAY(SELECT a.attname FROM unnest(k.conkey) WITH ORDINALITY x(num,ord)
                     JOIN pg_catalog.pg_attribute a ON a.attrelid=k.conrelid AND a.attnum=x.num
                     ORDER BY x.ord) AS columns,
               rn.nspname AS referenced_schema,rc.relname AS referenced_table,
               ARRAY(SELECT a.attname FROM unnest(k.confkey) WITH ORDINALITY x(num,ord)
                     JOIN pg_catalog.pg_attribute a ON a.attrelid=k.confrelid AND a.attnum=x.num
                     ORDER BY x.ord) AS referenced_columns,
               k.confupdtype AS update_action,k.confdeltype AS delete_action
          FROM pg_catalog.pg_constraint k
          JOIN pg_catalog.pg_class c ON c.oid=k.conrelid
          JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
          LEFT JOIN pg_catalog.pg_class rc ON rc.oid=k.confrelid
          LEFT JOIN pg_catalog.pg_namespace rn ON rn.oid=rc.relnamespace
         WHERE n.nspname=ANY(%s) OR n.nspname||'.'||c.relname=ANY(%s)
         ORDER BY n.nspname,c.relname,k.conname
    """, [scopes, names])
    return {"database": database, "read_only": True, "server_version": version,
            "relations": relations, "columns": columns, "constraints": constraints,
            "scope": "structure_only_not_data_or_runtime_validation"}
