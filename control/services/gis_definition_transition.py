"""Transactional migration from tenant GIS definitions to central v3 definitions."""
from __future__ import annotations

import json
from uuid import NAMESPACE_URL, uuid4, uuid5

from .gis_definitions import DefinitionError, rows

LEGACY_FORM = ('project_form_item', 'profile_form_item', 'form_item')
LEGACY_DEFINITION = (
    'scope_binding', 'capability_feature', 'capability', 'project_profile',
    'profile_field', 'profile_feature', 'profile', 'ref_code_value',
    'ref_code_group', 'meta_field_def', 'meta_feature_type',
)
CENTRAL_TABLES = (
    'definition_group', 'definition_layer_group', 'definition_layer', 'definition_layer_catalog',
    'definition_field', 'definition_field_layer', 'definition_code',
    'definition_group_scope', 'definition_group_layer',
    'definition_group_field', 'definition_rule', 'definition_rule_value',
    'definition_change_log', 'schema_change', 'schema_change_tenant',
)
V3_COMMENT = 'GeoFlow central GIS definitions v3; no tenant operational records'


def _exists(cur, relation):
    cur.execute('SELECT to_regclass(%s) IS NOT NULL', [relation])
    return bool(cur.fetchone()[0])


def inspect_tenant(cur):
    state = {}
    for table in (*LEGACY_FORM, *LEGACY_DEFINITION):
        if not _exists(cur, 'gis.' + table):
            state[table] = None
            continue
        cur.execute(f'SELECT count(*) FROM gis.{table}')
        state[table] = int(cur.fetchone()[0])
    return state


def source_snapshot(cur):
    """Read physical PostgreSQL schema first; legacy metadata only supplies labels."""
    layers = rows(cur, '''SELECT id::text,standard_name,physical_name,label,
        COALESCE(domain_code,''::text) AS domain_code,COALESCE(geometry_kind,''::text) AS geometry_kind,
        COALESCE(feature_role,'ASSET') AS feature_role,COALESCE(scope_type,'PROJECT') AS scope_type,
        COALESCE(sort_order,0) AS sort_order
        FROM gis.meta_feature_type WHERE active ORDER BY standard_name''')
    fields = rows(cur, '''SELECT ft.standard_name AS layer_name,ft.physical_name AS layer_table,
        a.attname AS physical_name,format_type(a.atttypid,a.atttypmod) AS storage_data_type,
        t.typname AS storage_udt_name,NOT a.attnotnull AS nullable,
        pg_get_expr(ad.adbin,ad.adrelid) AS storage_default,
        CASE WHEN a.atttypmod > 4 AND t.typname IN ('varchar','bpchar') THEN a.atttypmod-4 END AS max_length,
        CASE WHEN t.typname='numeric' AND a.atttypmod >= 0 THEN ((a.atttypmod-4)>>16)&65535 END AS precision,
        CASE WHEN t.typname='numeric' AND a.atttypmod >= 0 THEN (a.atttypmod-4)&65535 END AS scale,
        COALESCE(m.standard_name,upper(a.attname)) AS standard_name,
        COALESCE(m.label,replace(initcap(a.attname),'_',' ')) AS label,
        COALESCE(m.widget_type,'') AS legacy_widget_type,
        COALESCE(m.required_default,false) AS metadata_required,
        COALESCE(m.sort_order,a.attnum) AS sort_order,
        COALESCE(m.unit,'') AS unit,COALESCE(m.description,'') AS description,
        COALESCE(m.code_group_key,'') AS code_group_key,
        COALESCE(p.required,false) AS profile_required,
        COALESCE(p.readonly,false) AS profile_readonly,
        COALESCE(p.visible,true) AS profile_visible
      FROM gis.meta_feature_type ft
      JOIN pg_class c ON c.relname=ft.physical_name
      JOIN pg_namespace n ON n.oid=c.relnamespace AND n.nspname='gis'
      JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
      JOIN pg_type t ON t.oid=a.atttypid
      LEFT JOIN pg_attrdef ad ON ad.adrelid=c.oid AND ad.adnum=a.attnum
      LEFT JOIN gis.meta_field_def m ON m.feature_type_id=ft.id AND lower(m.physical_name)=lower(a.attname)
      LEFT JOIN LATERAL (
        SELECT bool_or(pf.required) AS required,bool_and(NOT pf.editable) AS readonly,
               bool_or(pf.visible) AS visible
          FROM gis.profile_field pf WHERE pf.field_def_id=m.id AND pf.enabled
      ) p ON true
     WHERE ft.active ORDER BY ft.standard_name,a.attnum''')
    bindings = rows(cur, '''SELECT DISTINCT f.standard_name,b.catalog_level,
        b.catalog_item_id::text FROM gis.scope_binding b
        JOIN gis.capability_feature cf ON cf.capability_id=b.capability_id AND cf.enabled
        JOIN gis.meta_feature_type f ON f.id=cf.feature_type_id AND f.active
        WHERE b.active ORDER BY f.standard_name,b.catalog_level,b.catalog_item_id::text''')
    codes = rows(cur, '''SELECT g.group_key,v.id::text,v.code,v.label,v.sort_order,
        (v.active AND (v.valid_from IS NULL OR v.valid_from<=CURRENT_DATE)
         AND (v.valid_to IS NULL OR v.valid_to>=CURRENT_DATE)) AS enabled
        FROM gis.ref_code_group g JOIN gis.ref_code_value v ON v.group_id=g.id
        WHERE g.active
        ORDER BY g.group_key,v.sort_order,v.code''')
    return {'layers': layers, 'fields': fields, 'bindings': bindings, 'codes': codes}


def merge_source_snapshots(snapshots):
    """Union tenant physical schemas, rejecting any conflicting storage truth."""
    if not snapshots:
        return None
    merged={'layers':[],'fields':[],'bindings':[],'codes':[]}
    layer_by_name={}; field_by_key={}; binding_by_key={}; code_by_key={}
    for source in snapshots:
        for layer in source.get('layers',[]):
            key=layer['standard_name']; previous=layer_by_name.get(key)
            if previous and any(previous.get(name)!=layer.get(name) for name in
                    ('physical_name','geometry_kind','feature_role','scope_type')):
                raise DefinitionError('Tenant 물리 Layer 매핑이 서로 달라 중앙 정의로 합칠 수 없습니다.')
            layer_by_name.setdefault(key,layer)
        for field in source.get('fields',[]):
            key=(field['layer_name'],field['physical_name']); previous=field_by_key.get(key)
            physical=('storage_data_type','storage_udt_name','nullable','storage_default',
                      'max_length','precision','scale')
            if previous and any(previous.get(name)!=field.get(name) for name in physical):
                raise DefinitionError('Tenant 물리 Field Schema가 서로 달라 중앙 정의로 합칠 수 없습니다.')
            field_by_key.setdefault(key,field)
        for binding in source.get('bindings',[]):
            binding_by_key[(binding['standard_name'],int(binding['catalog_level']),binding['catalog_item_id'])]=binding
        for code in source.get('codes',[]):
            key=(code['group_key'],code['code']); previous=code_by_key.get(key)
            if previous and previous['label']!=code['label']:
                raise DefinitionError('Tenant 참조코드 표시명이 서로 달라 중앙 정의로 합칠 수 없습니다.')
            code_by_key.setdefault(key,code)
    merged['layers']=sorted(layer_by_name.values(),key=lambda row:row['standard_name'])
    merged['fields']=sorted(field_by_key.values(),key=lambda row:(row['layer_name'],row['sort_order'],row['physical_name']))
    merged['bindings']=sorted(binding_by_key.values(),key=lambda row:(row['standard_name'],row['catalog_level'],row['catalog_item_id']))
    merged['codes']=sorted(code_by_key.values(),key=lambda row:(row['group_key'],row['sort_order'],row['code']))
    return merged


def _semantic_type(storage):
    value = str(storage or '').lower()
    if value in ('boolean', 'bool'):
        return 'boolean'
    if any(token in value for token in ('smallint', 'integer', 'bigint')):
        return 'integer'
    if any(token in value for token in ('numeric', 'decimal', 'real', 'double precision')):
        return 'decimal'
    if value == 'date':
        return 'date'
    if 'timestamp' in value:
        return 'datetime'
    return 'text'


def _widget(field, kind):
    if field.get('code_group_key'):
        return 'combo'
    raw = str(field.get('legacy_widget_type') or '').lower()
    aliases = {'lineedit':'text', 'textarea':'multiline', 'spinbox':'integer',
               'doublespinbox':'decimal', 'checkbox':'boolean', 'datetime':'datetime',
               'dateedit':'date', 'valuemap':'combo', 'combo':'combo'}
    value = aliases.get(raw, raw)
    allowed = {'text','multiline','integer','decimal','combo','boolean','date','datetime','hidden'}
    if value in allowed:
        return value
    return {'integer':'integer','decimal':'decimal','boolean':'boolean','date':'date',
            'datetime':'datetime'}.get(kind, 'text')


def _legacy_central_snapshot(cur):
    return {
        'groups': rows(cur, 'SELECT id::text,name FROM gis.definition_group'),
        'layers': rows(cur, 'SELECT standard_name,label FROM gis.definition_layer'),
        'layer_catalogs': rows(cur, 'SELECT layer_name,catalog_id::text FROM gis.definition_layer_catalog'),
        'fields': rows(cur, '''SELECT id::text,label,kind,max_length,precision,scale,sort_order,
            source_layer,physical_name FROM gis.definition_field'''),
        'field_layers': rows(cur, 'SELECT field_id::text,layer_name FROM gis.definition_field_layer'),
        'codes': rows(cur, 'SELECT id::text,field_id::text,code,label,sort_order FROM gis.definition_code'),
        'scopes': rows(cur, 'SELECT group_id::text,catalog_id::text FROM gis.definition_group_scope'),
        'group_layers': rows(cur, 'SELECT group_id::text,layer_name FROM gis.definition_group_layer'),
        'group_fields': rows(cur, '''SELECT group_id::text,layer_name,field_id::text,sort_order,required
            FROM gis.definition_group_field'''),
        'rules': rows(cur, '''SELECT r.id::text,r.source_field::text,r.source_code::text,r.target_field::text,
            COALESCE(array_agg(v.code_id::text ORDER BY v.code_id) FILTER(WHERE v.code_id IS NOT NULL),'{}') AS allowed
            FROM gis.definition_rule r LEFT JOIN gis.definition_rule_value v ON v.rule_id=r.id
            GROUP BY r.id'''),
    }


def _v3_central_snapshot(cur):
    return {
      'groups':rows(cur,'SELECT id::text,name FROM gis.definition_group'),
      'layers':rows(cur,'SELECT id::text,standard_name,label FROM gis.definition_layer'),
      'layer_catalogs':rows(cur,'''SELECT l.standard_name AS layer_name,lc.catalog_level,
        lc.catalog_item_id::text AS catalog_id FROM gis.definition_layer_catalog lc
        JOIN gis.definition_layer l ON l.id=lc.layer_id'''),
      'fields':rows(cur,'''SELECT f.id::text,f.label,f.kind,f.max_length,f.precision,f.scale,f.sort_order,
        l.standard_name AS source_layer,f.physical_name,f.widget_type,f.visible,f.required,f.readonly,
        f.default_value,f.layout,f.unit,f.description FROM gis.definition_field f
        LEFT JOIN gis.definition_layer l ON l.id=f.source_layer_id'''),
      'field_layers':rows(cur,'''SELECT fl.field_id::text,l.standard_name AS layer_name
        FROM gis.definition_field_layer fl JOIN gis.definition_layer l ON l.id=fl.layer_id'''),
      'codes':rows(cur,'SELECT id::text,field_id::text,code,label,sort_order,enabled FROM gis.definition_code'),
      'scopes':rows(cur,'''SELECT group_id::text,catalog_level,catalog_item_id::text AS catalog_id
        FROM gis.definition_group_scope'''),
      'group_layers':rows(cur,'''SELECT gl.group_id::text,l.standard_name AS layer_name
        FROM gis.definition_group_layer gl JOIN gis.definition_layer l ON l.id=gl.layer_id'''),
      'group_fields':rows(cur,'''SELECT gf.group_id::text,l.standard_name AS layer_name,gf.field_id::text,
        gf.sort_order,gf.required,gf.visible,gf.readonly,gf.layout FROM gis.definition_group_field gf
        JOIN gis.definition_layer l ON l.id=gf.layer_id'''),
      'rules':rows(cur,'''SELECT r.id::text,r.source_field::text,r.source_code::text,r.target_field::text,
        COALESCE(array_agg(v.code_id::text ORDER BY v.code_id) FILTER(WHERE v.code_id IS NOT NULL),'{}') AS allowed
        FROM gis.definition_rule r LEFT JOIN gis.definition_rule_value v ON v.rule_id=r.id GROUP BY r.id'''),
    }


def _drop_central(cur):
    for table in reversed(CENTRAL_TABLES):
        cur.execute(f'DROP TABLE gis.{table}')


def _create(cur, ddl):
    cur.execute(ddl)


def _restore_authored(cur, old, source):
    layer_ids = {}
    old_layer_labels = {row['standard_name']: row['label'] for row in old.get('layers', [])}
    old_layer_ids = {row['standard_name']: row.get('id') for row in old.get('layers', [])}
    for layer in source['layers']:
        lid = old_layer_ids.get(layer['standard_name']) or layer.get('id') or str(uuid4())
        layer_ids[layer['standard_name']] = lid
        cur.execute('''INSERT INTO gis.definition_layer
            (id,standard_name,physical_name,label,domain_code,geometry_kind,feature_role,scope_type,sort_order)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)''', [lid, layer['standard_name'], layer['physical_name'],
            old_layer_labels.get(layer['standard_name']) or layer['label'], layer['domain_code'],
            str(layer['geometry_kind'] or '').upper(),layer.get('feature_role','ASSET'),
            layer.get('scope_type','PROJECT'),layer['sort_order']])

    for group in old.get('groups', []):
        cur.execute('INSERT INTO gis.definition_group(id,name) VALUES (%s,%s)', [group['id'], group['name']])

    old_fields = {(row.get('source_layer'), row.get('physical_name')): row
                  for row in old.get('fields', []) if row.get('source_layer')}
    field_ids = {}
    code_groups = {}
    for field in source['fields']:
        key = (field['layer_name'], field['physical_name'])
        previous = old_fields.get(key, {})
        fid = previous.get('id') or str(uuid4())
        field_ids[key] = fid
        kind = _semantic_type(field['storage_data_type'])
        system = field['physical_name'] in ('id','project_id','geom','created_at','updated_at','created_by','updated_by','ext_data','row_version') or str(field['storage_data_type']).lower().startswith(('geometry','geography'))
        widget = previous.get('widget_type') or ('hidden' if system else _widget(field,kind))
        visible = previous.get('visible',bool(field['profile_visible']) and not system)
        readonly = previous.get('readonly',bool(field['profile_readonly']) or (system and field['physical_name']!='ext_data'))
        required = previous.get('required',bool(field['metadata_required'] or field['profile_required']) and not system)
        cur.execute('''INSERT INTO gis.definition_field
          (id,source_layer_id,physical_name,standard_name,label,storage_data_type,storage_udt_name,
           max_length,precision,scale,nullable,storage_default,kind,widget_type,visible,required,
           readonly,default_value,sort_order,unit,description,layout)
          VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s::jsonb)''',
          [fid, layer_ids[field['layer_name']], field['physical_name'], field['standard_name'],
           previous.get('label') or field['label'], field['storage_data_type'], field['storage_udt_name'],
           field['max_length'], field['precision'], field['scale'], field['nullable'],
           field['storage_default'], kind, widget, visible, required, readonly,
           json.dumps(previous.get('default_value')),previous.get('sort_order',field['sort_order']),
           previous.get('unit',field['unit']),previous.get('description',field['description']),
           json.dumps(previous.get('layout') or {})])
        cur.execute('INSERT INTO gis.definition_field_layer(field_id,layer_id) VALUES (%s,%s)',
                    [fid, layer_ids[field['layer_name']]])
        if field['code_group_key']:
            code_groups.setdefault(field['code_group_key'], []).append(fid)

    # Central-only additional fields survive the v2 -> v3 migration.
    for field in old.get('fields', []):
        if field.get('source_layer'):
            continue
        cur.execute('''INSERT INTO gis.definition_field
          (id,label,kind,max_length,precision,scale,widget_type,visible,required,readonly,default_value,
           sort_order,unit,description,layout)
          VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s::jsonb)''',
          [field['id'], field['label'], field['kind'],field['max_length'],field['precision'],field['scale'],
           field.get('widget_type') or _widget({},field['kind']),field.get('visible',True),
           field.get('required',False),field.get('readonly',False),json.dumps(field.get('default_value')),
           field['sort_order'],field.get('unit',''),field.get('description',''),json.dumps(field.get('layout') or {})])

    valid_fields = {r[0] for r in _fetch(cur, 'SELECT id::text FROM gis.definition_field')}
    existing_codes = set()
    for code in old.get('codes', []):
        if code['field_id'] not in valid_fields:
            continue
        cur.execute('''INSERT INTO gis.definition_code(id,field_id,code,label,sort_order,enabled)
            VALUES (%s,%s,%s,%s,%s,%s)''', [code['id'],code['field_id'],code['code'],code['label'],code['sort_order'],code.get('enabled',True)])
        existing_codes.add((code['field_id'], code['code']))
    for code in source['codes']:
        for fid in code_groups.get(code['group_key'], []):
            if (fid, code['code']) in existing_codes:
                continue
            cur.execute('''INSERT INTO gis.definition_code(id,field_id,code,label,sort_order,enabled)
                VALUES (%s,%s,%s,%s,%s,%s)''', [str(uuid5(NAMESPACE_URL,'geoflow:code:'+fid+':'+str(code.get('id') or code['code']))),fid,code['code'],code['label'],code['sort_order'],code['enabled']])

    bindings = {(row['standard_name'], int(row['catalog_level']), row['catalog_item_id'])
                for row in source['bindings']}
    bindings.update((row['layer_name'],int(row.get('catalog_level',2)),row['catalog_id']) for row in old.get('layer_catalogs', []))
    for name, level, item in sorted(bindings):
        if name in layer_ids:
            cur.execute('INSERT INTO gis.definition_layer_catalog(layer_id,catalog_level,catalog_item_id) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING',
                        [layer_ids[name],level,item])

    for row in old.get('scopes', []):
        cur.execute('INSERT INTO gis.definition_group_scope(group_id,catalog_level,catalog_item_id) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING', [row['group_id'],row.get('catalog_level',2),row['catalog_id']])
    for row in old.get('field_layers', []):
        lid = layer_ids.get(row['layer_name'])
        if lid and row['field_id'] in valid_fields:
            cur.execute('INSERT INTO gis.definition_field_layer(field_id,layer_id) VALUES (%s,%s) ON CONFLICT DO NOTHING', [row['field_id'],lid])
    for row in old.get('group_layers', []):
        lid = layer_ids.get(row['layer_name'])
        if lid:
            cur.execute('INSERT INTO gis.definition_group_layer(group_id,layer_id) VALUES (%s,%s) ON CONFLICT DO NOTHING', [row['group_id'],lid])
    for row in old.get('group_fields', []):
        lid = layer_ids.get(row['layer_name'])
        if lid and row['field_id'] in valid_fields:
            cur.execute('''INSERT INTO gis.definition_group_field
                (group_id,layer_id,field_id,sort_order,required,visible,readonly,layout)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT DO NOTHING''',
                [row['group_id'],lid,row['field_id'],row['sort_order'],row['required'],
                 row.get('visible'),row.get('readonly'),json.dumps(row.get('layout') or {})])
    valid_codes = {r[0] for r in _fetch(cur, 'SELECT id::text FROM gis.definition_code')}
    for rule in old.get('rules', []):
        if not {rule['source_field'],rule['target_field']} <= valid_fields or rule['source_code'] not in valid_codes:
            continue
        cur.execute('INSERT INTO gis.definition_rule VALUES (%s,%s,%s,%s)',
                    [rule['id'],rule['source_field'],rule['source_code'],rule['target_field']])
        for code_id in rule['allowed']:
            if code_id in valid_codes:
                cur.execute('INSERT INTO gis.definition_rule_value VALUES (%s,%s,%s)', [rule['id'],rule['target_field'],code_id])


def _fetch(cur, sql, params=()):
    cur.execute(sql, params)
    return cur.fetchall()


def type_correction_count(cur,source):
    if not _exists(cur,'gis.definition_field'): return len(source.get('fields',[]))
    cur.execute("SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='gis' AND table_name='definition_field' AND column_name='source_layer_id')")
    if cur.fetchone()[0]:
        current=rows(cur,'''SELECT l.standard_name AS layer_name,f.physical_name,f.kind
            FROM gis.definition_field f JOIN gis.definition_layer l ON l.id=f.source_layer_id''')
    else:
        current=rows(cur,'''SELECT source_layer AS layer_name,physical_name,kind
            FROM gis.definition_field WHERE source_layer IS NOT NULL''')
    kinds={(row['layer_name'],row['physical_name']):row['kind'] for row in current}
    return sum(1 for field in source.get('fields',[]) if
               kinds.get((field['layer_name'],field['physical_name'])) != _semantic_type(field['storage_data_type']))


def bootstrap(cur, source, ddl):
    """Create v3 or transactionally rebuild v2 while preserving authored UUIDs."""
    cur.execute("SELECT pg_advisory_xact_lock(hashtext('geoflow.central.gis.definitions'))")
    present = [_exists(cur, 'gis.' + table) for table in CENTRAL_TABLES]
    if any(present) and not all(present):
        raise DefinitionError('중앙 정의 구조가 일부만 존재합니다. 자동 덮어쓰기를 중지했습니다.')
    if not source['layers'] or not source['fields']:
        raise DefinitionError('실제 GIS 물리 스키마를 확인할 수 없습니다.')
    old={}
    if all(present):
        cur.execute("SELECT obj_description('gis.definition_group'::regclass)")
        comment = cur.fetchone()[0]
        if comment not in (V3_COMMENT, 'GeoFlow central GIS definitions v2; no tenant operational records'):
            raise DefinitionError('알 수 없는 중앙 정의 구조입니다.')
        old=_v3_central_snapshot(cur) if comment==V3_COMMENT else _legacy_central_snapshot(cur)
        _drop_central(cur)
    _create(cur, ddl)
    _restore_authored(cur, old, source)
    return not any(present)


def prepare_project_runtime(cur):
    if not _exists(cur, 'gis.project_definition'):
        cur.execute('''CREATE TABLE gis.project_definition (
          project_id uuid PRIMARY KEY REFERENCES prj.projects(id), group_id uuid,
          additions jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(additions)='object'),
          private_items jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(private_items)='object'),
          overrides jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(overrides)='object'),
          definition_revision text)''')
    else:
        cur.execute("ALTER TABLE gis.project_definition ADD COLUMN IF NOT EXISTS overrides jsonb NOT NULL DEFAULT '{}'::jsonb")
        cur.execute('ALTER TABLE gis.project_definition ADD COLUMN IF NOT EXISTS definition_revision text')
    cur.execute("COMMENT ON TABLE gis.project_definition IS 'GeoFlow tenant project selection v3; central definition UUIDs only'")


def migrate_project_config(cur, layer_ids):
    prepare_project_runtime(cur)
    valid_ids=set(layer_ids.values())
    cur.execute('SELECT project_id::text,additions,private_items FROM gis.project_definition FOR UPDATE')
    for project_id, additions, private_items in cur.fetchall():
        if isinstance(additions,str): additions=json.loads(additions)
        if isinstance(private_items,str): private_items=json.loads(private_items)
        converted={}
        for field_id,values in (additions or {}).items():
            mapped=[]
            for value in values if isinstance(values,list) else []:
                target=layer_ids.get(value,value)
                if target in valid_ids: mapped.append(target)
            if mapped: converted[field_id]=sorted(set(mapped))
        private={}
        for field_id,value in (private_items or {}).items():
            if not isinstance(value,dict): continue
            item=dict(value); target=item.pop('source_layer',None) or item.get('source_layer_id')
            target=layer_ids.get(target,target)
            if target not in valid_ids: continue
            item['source_layer_id']=target; private[field_id]=item
        cur.execute('UPDATE gis.project_definition SET additions=%s::jsonb,private_items=%s::jsonb WHERE project_id=%s',
                    [json.dumps(converted),json.dumps(private),project_id])


def migrate_runtime_fks(cur, layer_ids):
    """Move runtime lineage to stable central layer UUIDs before metadata removal."""
    if _exists(cur, 'gis.survey_link'):
        cur.execute('ALTER TABLE gis.survey_link ADD COLUMN IF NOT EXISTS layer_id uuid')
        if _exists(cur, 'gis.meta_feature_type'):
            cur.execute('''UPDATE gis.survey_link sl SET layer_id=m.layer_id::uuid
                FROM gis.meta_feature_type ft JOIN (SELECT key AS standard_name,value AS layer_id
                FROM jsonb_each_text(%s::jsonb)) m ON m.standard_name=ft.standard_name
                WHERE sl.feature_type_id=ft.id AND sl.layer_id IS NULL''', [json.dumps(layer_ids)])
        cur.execute('ALTER TABLE gis.survey_link ALTER COLUMN layer_id SET NOT NULL')
        cur.execute('ALTER TABLE gis.survey_link DROP CONSTRAINT IF EXISTS survey_link_feature_type_id_fkey')
        cur.execute('ALTER TABLE gis.survey_link DROP COLUMN IF EXISTS feature_type_id')
        cur.execute('''CREATE UNIQUE INDEX IF NOT EXISTS survey_link_survey_layer_target_uq
            ON gis.survey_link(survey_id,layer_id,target_id)''')
        cur.execute('''CREATE INDEX IF NOT EXISTS survey_link_layer_target_idx
            ON gis.survey_link(layer_id,target_id)''')
    if _exists(cur, 'gis.import_batch'):
        cur.execute('ALTER TABLE gis.import_batch ADD COLUMN IF NOT EXISTS definition_revision text')
        cur.execute('ALTER TABLE gis.import_batch DROP CONSTRAINT IF EXISTS import_batch_profile_id_fkey')
        cur.execute('ALTER TABLE gis.import_batch DROP COLUMN IF EXISTS profile_id')


def retire_legacy(cur):
    """Drop only GIS definition tables, in dependency order and without CASCADE."""
    for table in LEGACY_FORM:
        if _exists(cur, 'gis.' + table):
            cur.execute(f'DROP TABLE gis.{table}')
    for table in LEGACY_DEFINITION:
        if _exists(cur, 'gis.' + table):
            cur.execute(f'DROP TABLE gis.{table}')
