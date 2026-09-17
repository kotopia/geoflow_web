#!/usr/bin/env python3
"""Read-only structural inventory; never export feature or operational records.

Run with the deployed Django runtime. Output is safe structural metadata and
aggregate counts, not a backup. Database credentials/exception messages/DSNs and
project, employee, group names or identifiers are deliberately excluded.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone

METADATA_TABLES = frozenset({
    'definition_group', 'definition_layer', 'definition_layer_catalog',
    'definition_field', 'definition_field_layer', 'definition_code',
    'definition_group_scope', 'definition_group_layer', 'definition_group_field',
    'definition_rule', 'definition_rule_value', 'project_definition',
    'meta_feature_type', 'meta_field_def', 'profile', 'profile_feature',
    'profile_field', 'project_profile', 'ref_code_group', 'ref_code_value',
    'scope_binding', 'capability', 'capability_feature',
    'form_item', 'profile_form_item', 'project_form_item',
})
STANDARD_FIELD_KEYS = ('physical_name', 'standard_name', 'label', 'data_type',
                       'kind', 'widget_type', 'required_default', 'sort_order',
                       'max_length', 'precision', 'scale', 'core_field', 'unit')


def rows(cur, query, params=()):
    cur.execute(query, params)
    return [dict(zip([c[0] for c in cur.description], r)) for r in cur.fetchall()]


def json_object(value):
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError('invalid_metadata_object')
    return value


def default_summary(value):
    """Preserve safe schema defaults, redact arbitrary string literals."""
    if value is None:
        return None
    if re.fullmatch(r"(?:true|false|NULL|[-+]?\d+(?:\.\d+)?|now\(\)|gen_random_uuid\(\)|uuid_generate_v4\(\))(?:::[a-z ]+)?", value, re.I):
        return value
    return '[expression present; value not exported]'


def inventory(cur):
    # Transaction is already read-only before the first SELECT, on each DB.
    cur.execute('SHOW transaction_read_only')
    if cur.fetchone()[0] != 'on':
        raise RuntimeError('read_only_required')
    relations = rows(cur, """SELECT c.relname AS name,c.relkind AS kind
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='gis' AND c.relkind IN ('r','p','v','m') ORDER BY c.relname""")
    present = {r['name'] for r in relations if r['kind'] in ('r', 'p')}
    columns = rows(cur, """SELECT table_name,column_name,ordinal_position,data_type,udt_name,
        is_nullable,character_maximum_length,numeric_precision,numeric_scale,column_default
        FROM information_schema.columns WHERE table_schema='gis'
        ORDER BY table_name,ordinal_position""")
    for column in columns:
        column['column_default'] = default_summary(column['column_default'])
    constraints = rows(cur, """SELECT n.nspname AS table_schema,c.relname AS table_name,k.conname AS name,k.contype AS type,
        k.conkey AS columns,k.confkey AS referenced_columns,
        rn.nspname AS referenced_schema,rc.relname AS referenced_table
        FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        LEFT JOIN pg_class rc ON rc.oid=k.confrelid
        LEFT JOIN pg_namespace rn ON rn.oid=rc.relnamespace
        WHERE n.nspname='gis' OR rn.nspname='gis'
        ORDER BY c.relname,k.conname""")
    # Count only known definition/metadata tables, never facility or business rows.
    counts = {}
    for table in sorted(present & METADATA_TABLES):
        cur.execute('SELECT count(*) FROM gis.' + table)
        counts[table] = cur.fetchone()[0]
    result = {'read_only': True, 'relations': relations, 'columns': columns,
              'constraints': constraints, 'metadata_counts': counts}
    cur.execute("SELECT to_regclass('catalog.category_node') IS NOT NULL")
    if cur.fetchone()[0]:
        result['catalog_counts'] = rows(cur, """SELECT level,active,count(*) AS count
            FROM catalog.category_node GROUP BY level,active ORDER BY level,active""")
        result['catalog_structure'] = rows(cur, """SELECT table_name,column_name,data_type,is_nullable
            FROM information_schema.columns WHERE table_schema='catalog'
            ORDER BY table_name,ordinal_position""")
        result['work_types'] = rows(cur, """SELECT code,name,active FROM catalog.category_node
            WHERE level=2 ORDER BY code""")
    if 'definition_layer' in present:
        result['central_layers'] = rows(cur, 'SELECT standard_name,label FROM gis.definition_layer ORDER BY standard_name')
    if 'definition_field' in present:
        result['central_standard_fields'] = []
        for row in rows(cur, """SELECT source_layer,to_jsonb(f) AS field FROM gis.definition_field f
                WHERE source_layer IS NOT NULL AND physical_name IS NOT NULL
                ORDER BY source_layer,physical_name"""):
            field = json_object(row['field'])
            result['central_standard_fields'].append({'layer': row['source_layer'],
                **{key: field.get(key) for key in STANDARD_FIELD_KEYS}})
        result['central_field_kinds'] = rows(cur, """SELECT kind,(physical_name IS NOT NULL) AS standard,
            count(*) AS count FROM gis.definition_field GROUP BY kind,(physical_name IS NOT NULL)
            ORDER BY kind,standard""")
    if {'definition_code', 'definition_field'} <= present:
        result['code_coverage'] = rows(cur, """SELECT f.source_layer AS layer,f.physical_name AS field,
            count(c.id) AS code_count FROM gis.definition_field f
            LEFT JOIN gis.definition_code c ON c.field_id=f.id WHERE f.physical_name IS NOT NULL
            GROUP BY f.source_layer,f.physical_name ORDER BY f.source_layer,f.physical_name""")
    if {'definition_rule','definition_rule_value','definition_field','definition_code'} <= present:
        result['rule_integrity'] = rows(cur, """SELECT count(*) AS rules,
            count(*) FILTER(WHERE s.id IS NULL OR t.id IS NULL OR sc.id IS NULL) AS broken_sources,
            count(*) FILTER(WHERE NOT EXISTS(SELECT 1 FROM gis.definition_rule_value v WHERE v.rule_id=r.id)) AS empty_targets
            FROM gis.definition_rule r LEFT JOIN gis.definition_field s ON s.id=r.source_field
            LEFT JOIN gis.definition_field t ON t.id=r.target_field
            LEFT JOIN gis.definition_code sc ON sc.id=r.source_code AND sc.field_id=r.source_field""")
    if 'meta_feature_type' in present:
        result['tenant_layers'] = rows(cur, """SELECT standard_name,physical_name,label,geometry_kind,
            active,sort_order FROM gis.meta_feature_type ORDER BY standard_name""")
    if {'meta_feature_type','meta_field_def'} <= present:
        result['tenant_standard_fields'] = []
        for row in rows(cur, """SELECT l.standard_name AS layer,to_jsonb(f) AS field
            FROM gis.meta_field_def f JOIN gis.meta_feature_type l ON l.id=f.feature_type_id
            ORDER BY l.standard_name,f.physical_name"""):
            field = json_object(row['field'])
            result['tenant_standard_fields'].append({'layer': row['layer'],
                **{key: field.get(key) for key in STANDARD_FIELD_KEYS},
                'has_reference_code': bool(field.get('code_group_key'))})
    if {'capability', 'capability_feature', 'meta_feature_type'} <= present:
        result['capability_layers'] = rows(cur, """SELECT c.code AS capability,c.active,
            l.standard_name AS layer,cf.enabled,cf.required,cf.sort_order
            FROM gis.capability c JOIN gis.capability_feature cf ON cf.capability_id=c.id
            JOIN gis.meta_feature_type l ON l.id=cf.feature_type_id
            ORDER BY c.code,l.standard_name""")
    if 'scope_binding' in present:
        result['scope_binding_levels'] = rows(cur, """SELECT catalog_level,active,count(*) AS count,
            count(*) FILTER(WHERE catalog_code_cache IS NULL) AS missing_cached_codes
            FROM gis.scope_binding GROUP BY catalog_level,active ORDER BY catalog_level,active""")
    if {'profile_field', 'meta_field_def', 'meta_feature_type'} <= present:
        result['profile_field_settings'] = rows(cur, """SELECT
            dense_rank() OVER(ORDER BY pf.profile_id) AS profile_number,
            l.standard_name AS layer,f.physical_name AS field,
            pf.enabled,pf.required,pf.editable,pf.visible,pf.sort_order
            FROM gis.profile_field pf JOIN gis.meta_field_def f ON f.id=pf.field_def_id
            JOIN gis.meta_feature_type l ON l.id=f.feature_type_id
            ORDER BY pf.profile_id,l.standard_name,f.physical_name""")
    if 'profile_field' in present:
        result['profile_flags'] = rows(cur, """SELECT enabled,required,editable,visible,count(*) AS count
            FROM gis.profile_field GROUP BY enabled,required,editable,visible
            ORDER BY enabled,required,editable,visible""")
    if 'project_definition' in present:
        result['project_configuration_counts'] = rows(cur, """SELECT count(*) AS configured_projects,
            count(*) FILTER(WHERE group_id IS NOT NULL) AS with_group,
            count(*) FILTER(WHERE additions <> '{}'::jsonb) AS with_additions,
            count(*) FILTER(WHERE private_items <> '{}'::jsonb) AS with_private_items
            FROM gis.project_definition""")
    return result


def failure_summary(exc, stage):
    """Return bounded categories only; never exception text/args, DSN or diagnostics."""
    categories = {
        'TenantDBCredentialError': 'credential_resolution_failed',
        'Http404': 'tenant_configuration_unavailable',
        'OperationalError': 'connection_or_database_unavailable',
        'InterfaceError': 'database_interface_failed',
        'ProgrammingError': 'schema_or_query_mismatch',
        'ValueError': 'invalid_metadata',
    }
    category = next((categories[c.__name__] for c in type(exc).__mro__
                     if c.__name__ in categories), 'unexpected_inspection_error')
    result = {'stage': stage, 'category': category}
    sqlstate = getattr(exc, 'pgcode', None)
    if isinstance(sqlstate, str) and re.fullmatch(r'[0-9A-Z]{5}', sqlstate):
        result['sqlstate'] = sqlstate
    return result


def inspect_tenants(tenant_ids, cursor_factory):
    results = []
    for number, group_id in enumerate(tenant_ids, 1):
        stage = 'connect'
        try:
            with cursor_factory(group_id, write=False) as cur:
                stage = 'inventory'
                data = inventory(cur)
                stage = 'close'
            results.append({'store': number, 'status': 'ok', 'inventory': data})
        except Exception as exc:
            results.append({'store': number, 'status': 'inspection_failed',
                            'failure': failure_summary(exc, stage)})
    return results


def main():
    # Applies even to initial Django connection setup and the tenant registry read.
    os.environ['PGOPTIONS'] = os.environ.get('PGOPTIONS', '') + ' -c default_transaction_read_only=on'
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'geoflow_project.settings')
    import django
    django.setup()
    from django.db import connections, transaction
    from control.models import GroupDBConfig
    from control.services.gis_admin import tenant_cursor

    result = {'report_version': 2, 'observed_at': datetime.now(timezone.utc).isoformat(),
              'tenants': [], 'complete': False}
    with transaction.atomic(using='default'), connections['default'].cursor() as cur:
        cur.execute('SET TRANSACTION READ ONLY')
        cur.execute("SET LOCAL statement_timeout='15s'")
        cur.execute("SET LOCAL lock_timeout='3s'")
        result['central'] = inventory(cur)
        # Never emit tenant config, names, aliases, endpoints, or IDs.
        tenant_ids = list(GroupDBConfig.objects.using('default')
                          .filter(group__status='active').order_by('group_id')
                          .values_list('group_id', flat=True))
    result['tenants'] = inspect_tenants(tenant_ids, tenant_cursor)
    failed = any(t['status'] != 'ok' for t in result['tenants'])
    result['complete'] = not failed
    print('GIS_FORM_INVENTORY_BEGIN')
    print(json.dumps(result, ensure_ascii=True, sort_keys=True, default=str))
    print('GIS_FORM_INVENTORY_END')
    return 2 if failed else 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        # DB errors can contain credentials, DSNs or data; never print tracebacks.
        print('gis_form_inventory_blocker=inspection_failed', file=sys.stderr)
        raise SystemExit(2) from None
