"""Explicit, repeatable central bootstrap and empty legacy-table retirement."""
import json
from pathlib import Path
from uuid import uuid4
from .gis_definitions import rows, ready, DefinitionError

LEGACY=('project_form_item','profile_form_item','form_item')
CENTRAL_TABLES=('definition_group','definition_layer','definition_layer_catalog','definition_field',
 'definition_field_layer','definition_code','definition_group_scope','definition_group_layer',
 'definition_group_field','definition_rule','definition_rule_value')


def inspect_tenant(cur):
    # Never delete an unknown populated definition store, even though test data deletion is authorized.
    state={}
    for table in LEGACY:
        cur.execute('SELECT to_regclass(%s)', ['gis.'+table])
        if not cur.fetchone()[0]: state[table]=None; continue
        cur.execute(f'LOCK TABLE gis.{table} IN ACCESS EXCLUSIVE MODE')
        cur.execute(f'SELECT count(*) FROM gis.{table}')
        count=cur.fetchone()[0]
        if count: raise DefinitionError('기존 폼 정의에 데이터가 있어 자동 삭제를 중지했습니다. 데이터 전환이 필요합니다.')
        state[table]=rows(cur,"""SELECT column_name,data_type,is_nullable,column_default FROM information_schema.columns
            WHERE table_schema='gis' AND table_name=%s ORDER BY ordinal_position""",[table])
    return state


def source_snapshot(cur):
    return {
      'layers':rows(cur,'SELECT id::text,standard_name,label FROM gis.meta_feature_type WHERE active ORDER BY standard_name'),
      'bindings':rows(cur,'''SELECT DISTINCT f.standard_name,b.catalog_item_id::text
        FROM gis.scope_binding b JOIN gis.capability_feature cf ON cf.capability_id=b.capability_id AND cf.enabled
        JOIN gis.meta_feature_type f ON f.id=cf.feature_type_id AND f.active
        WHERE b.active AND b.catalog_level=2 ORDER BY f.standard_name,b.catalog_item_id::text'''),
      'fields':rows(cur,'''SELECT f.standard_name AS layer_name,d.physical_name,d.label,d.data_type,d.sort_order,d.code_group_key
         FROM gis.meta_field_def d JOIN gis.meta_feature_type f ON f.id=d.feature_type_id AND f.active
         ORDER BY f.standard_name,d.physical_name'''),
      'codes':rows(cur,'''SELECT g.group_key,v.code,v.label,v.sort_order FROM gis.ref_code_group g
         JOIN gis.ref_code_value v ON v.group_id=g.id WHERE g.active AND v.active
         AND (v.valid_from IS NULL OR v.valid_from<=CURRENT_DATE)
         AND (v.valid_to IS NULL OR v.valid_to>=CURRENT_DATE) ORDER BY g.group_key,v.sort_order,v.code''')}


def bootstrap(cur, source, ddl):
    cur.execute("SELECT pg_advisory_xact_lock(hashtext('geoflow.central.gis.definitions'))")
    existing=[]
    for table in CENTRAL_TABLES:
        cur.execute('SELECT to_regclass(%s) IS NOT NULL',['gis.'+table]);existing.append(cur.fetchone()[0])
    if any(existing):
        if not all(existing): raise DefinitionError('중앙 정의 구조가 일부만 존재합니다. 자동 덮어쓰기를 중지했습니다.')
        cur.execute("SELECT obj_description('gis.definition_group'::regclass)")
        if cur.fetchone()[0]!='GeoFlow central GIS definitions v2; no tenant operational records':
            raise DefinitionError('알 수 없는 중앙 정의 구조입니다.')
        return False
    if not source['layers'] or not source['fields']: raise DefinitionError('초기화할 기존 GIS 메타데이터가 없습니다.')
    cur.execute(ddl)
    for layer in source['layers']:
        cur.execute('INSERT INTO gis.definition_layer VALUES (%s,%s)',[layer['standard_name'],layer['label']])
    for binding in source['bindings']:
        cur.execute('SELECT 1 FROM catalog.category_node WHERE id=%s AND level=2 AND active',[binding['catalog_item_id']])
        if not cur.fetchone(): raise DefinitionError('기존 GIS 업무범위와 중앙 catalog가 일치하지 않습니다.')
        cur.execute('INSERT INTO gis.definition_layer_catalog VALUES (%s,%s)',[binding['standard_name'],binding['catalog_item_id']])
    for field in source['fields']:
        fid=str(uuid4()); typ=field['data_type'].lower()
        kind='boolean' if typ in ('bool','boolean') else 'integer' if typ in ('integer','int','int2','int4','int8','smallint','bigint') else 'decimal' if typ in ('numeric','decimal','float','double precision','real','float8','float4') else 'date' if typ in ('date','timestamp','timestamptz') else 'text'
        # Existing coded identifiers remain text regardless of storage coercion.
        if field['code_group_key']: kind='text'
        cur.execute('''INSERT INTO gis.definition_field(id,label,kind,sort_order,source_layer,physical_name)
            VALUES (%s,%s,%s,%s,%s,%s)''',[fid,field['label'],kind,field['sort_order'],field['layer_name'],field['physical_name']])
        cur.execute('INSERT INTO gis.definition_field_layer VALUES (%s,%s)',[fid,field['layer_name']])
        for code in source['codes']:
            if field['code_group_key'] and code['group_key']==field['code_group_key']:
                cur.execute('INSERT INTO gis.definition_code VALUES (%s,%s,%s,%s,%s)',
                    [str(uuid4()),fid,code['code'],code['label'],code['sort_order']])
    return True


def retire_empty_legacy(cur):
    state=inspect_tenant(cur)
    cur.execute("SELECT to_regclass('gis.project_definition')")
    if not cur.fetchone()[0]:
        cur.execute('''CREATE TABLE gis.project_definition (
            project_id uuid PRIMARY KEY REFERENCES prj.projects(id), group_id uuid,
            additions jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(additions)='object'),
            private_items jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(private_items)='object'))''')
        cur.execute("COMMENT ON TABLE gis.project_definition IS 'GeoFlow tenant project selection v2; central definition UUIDs'")
    else:
        cur.execute("SELECT obj_description('gis.project_definition'::regclass)")
        if cur.fetchone()[0]!='GeoFlow tenant project selection v2; central definition UUIDs':
            raise DefinitionError('프로젝트 구성 테이블 구조를 확인하세요.')
    for table in LEGACY:
        # Deliberately no CASCADE: unknown inbound FK/view dependencies abort the transaction.
        if state[table] is not None: cur.execute(f'DROP TABLE gis.{table}')
    return state
