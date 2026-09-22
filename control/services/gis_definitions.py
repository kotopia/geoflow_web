"""Authoring service for the central, platform-independent GIS definition."""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from geoflow_ops.gis.form_definitions import DefinitionError, identifier, rows, text

KINDS = {'text':'문자','integer':'정수','decimal':'소수','boolean':'유무','date':'날짜',
         'datetime':'일시','photo':'사진','relation':'관계형'}
WIDGETS = {'text':'한 줄 문자','multiline':'여러 줄 문자','integer':'정수','decimal':'소수',
           'combo':'선택 목록','boolean':'체크','date':'날짜','datetime':'일시',
           'photo':'사진','relation':'관계형','hidden':'숨김'}


def ready(cur):
    cur.execute("SELECT to_regclass('gis.definition_rule_value') IS NOT NULL AND "
                "EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='gis' "
                "AND table_name='definition_layer' AND column_name='id')")
    return bool(cur.fetchone()[0])


def number(value, default=0):
    try:
        result = int(value if value not in (None, '') else default)
    except (TypeError, ValueError):
        raise DefinitionError('숫자 입력을 확인하세요.') from None
    if not -2147483648 <= result <= 2147483647:
        raise DefinitionError('숫자 범위를 확인하세요.')
    return result


def boolean(value, default=False):
    if value is None:
        return default
    return value in (True, 'true', 'on', '1', 1)


def json_object(value, label):
    if value in (None, ''):
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            raise DefinitionError(label + ' JSON을 확인하세요.') from None
    if not isinstance(value, dict):
        raise DefinitionError(label + '은 객체여야 합니다.')
    return value


def field_values(data):
    """Retain the compact legacy helper contract used by existing callers/tests."""
    kind = data.get('kind')
    if kind not in KINDS:
        raise DefinitionError('필드 유형을 선택하세요.')
    length = number(data.get('max_length'),255) if kind=='text' else None
    precision = number(data.get('precision'),12) if kind=='decimal' else None
    scale = number(data.get('scale'),2) if kind=='decimal' else None
    if length is not None and not 1 <= length <= 100000:
        raise DefinitionError('문자 길이는 1~100000입니다.')
    if precision is not None and (precision == 0 or not 0 <= scale <= precision <= 38):
        raise DefinitionError('전체 자릿수는 1~38, 소수 자릿수는 전체 자릿수 이하입니다.')
    return [text(data.get('label')),kind,length,precision,scale,number(data.get('sort_order'))]


def one(cur, sql, params, message='대상을 찾을 수 없습니다.'):
    cur.execute(sql, params)
    result = cur.fetchone()
    if not result:
        raise DefinitionError(message)
    return result


def _catalog_exists(cur, level, item):
    if level == 2:
        return bool(one(cur, 'SELECT 1 FROM catalog.category_node WHERE id=%s AND level=2 AND active', [item]))
    # L3/L4 are option IDs in the existing catalog model, not invented nodes.
    return bool(one(cur, '''SELECT 1 FROM catalog.category_facet_option o
        JOIN catalog.category_facet f ON f.id=o.facet_id
        WHERE o.id=%s AND o.active AND f.active''', [item]))


def _codes_allowed(cur, field):
    kind = one(cur, 'SELECT kind FROM gis.definition_field WHERE id=%s', [field])[0]
    if kind not in ('text','integer','decimal','boolean'):
        raise DefinitionError('이 유형에는 참조코드를 연결할 수 없습니다.')
    return kind


def _form_metadata(data, *, kind):
    widget = data.get('widget_type') or {'integer':'integer','decimal':'decimal','boolean':'boolean',
        'date':'date','datetime':'datetime','photo':'photo','relation':'relation'}.get(kind,'text')
    if widget not in WIDGETS:
        raise DefinitionError('위젯 유형을 선택하세요.')
    return [widget, boolean(data.get('visible'), True), boolean(data.get('required')),
            boolean(data.get('readonly'))]


def _layout_json(data):
    """Validate layout only for the additional-field editor that owns it."""
    return json.dumps(json_object(data.get('layout'), '레이아웃'), ensure_ascii=False)


def mutate(cur, data):
    action = data.get('action','')
    actions = {'group','field','standard_field','layer','code','scope','group_layer','group_field',
               'field_layer','rule','delete_group','delete_field','delete_code','delete_scope',
               'delete_group_layer','delete_group_field','delete_field_layer','delete_rule'}
    if action not in actions:
        raise DefinitionError('지원하지 않는 요청입니다.')
    cur.execute("SELECT pg_advisory_xact_lock(hashtext('geoflow.central.gis.definitions'))")
    uid = identifier(data['id']) if data.get('id') else str(uuid4())
    if action == 'group':
        cur.execute('''INSERT INTO gis.definition_group(id,name) VALUES (%s,%s)
            ON CONFLICT(id) DO UPDATE SET name=EXCLUDED.name''', [uid,text(data.get('label'))])
    elif action == 'layer':
        layer = identifier(data.get('id'))
        cur.execute('''UPDATE gis.definition_layer SET label=%s,sort_order=%s,active=%s WHERE id=%s''',
                    [text(data.get('label')),number(data.get('sort_order')),boolean(data.get('active'),True),layer])
        if cur.rowcount != 1:
            raise DefinitionError('표준 레이어를 찾을 수 없습니다.')
    elif action in ('field','standard_field'):
        values = field_values(data)
        meta = _form_metadata(data, kind=values[1])
        if action == 'standard_field':
            one(cur, 'SELECT 1 FROM gis.definition_field WHERE id=%s AND source_layer_id IS NOT NULL', [uid])
            cur.execute('''UPDATE gis.definition_field SET label=%s,kind=%s,widget_type=%s,
              visible=%s,required=%s,readonly=%s,sort_order=%s WHERE id=%s''',
              [values[0],values[1],*meta,values[5],uid])
        else:
            if data.get('id'):
                old = one(cur,'SELECT kind,source_layer_id FROM gis.definition_field WHERE id=%s',[uid])
                if old[1]:
                    raise DefinitionError('표준 필드는 표준 레이어/필드 화면에서 편집하세요.')
                if old[0] != values[1]:
                    cur.execute('SELECT 1 FROM gis.definition_code WHERE field_id=%s LIMIT 1',[uid])
                    if cur.fetchone():
                        raise DefinitionError('참조코드를 먼저 정리한 후 유형을 변경하세요.')
            cur.execute('''INSERT INTO gis.definition_field
              (id,label,kind,max_length,precision,scale,sort_order,widget_type,visible,required,readonly,layout)
              VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
              ON CONFLICT(id) DO UPDATE SET label=EXCLUDED.label,kind=EXCLUDED.kind,
              max_length=EXCLUDED.max_length,precision=EXCLUDED.precision,scale=EXCLUDED.scale,
              sort_order=EXCLUDED.sort_order,widget_type=EXCLUDED.widget_type,visible=EXCLUDED.visible,
              required=EXCLUDED.required,readonly=EXCLUDED.readonly,layout=EXCLUDED.layout''',
              [uid,*values,*meta,_layout_json(data)])
    elif action == 'code':
        field = identifier(data.get('field')); kind = _codes_allowed(cur,field); code = text(data.get('code'))
        if kind == 'integer':
            try: int(code)
            except ValueError: raise DefinitionError('정수형 코드를 입력하세요.') from None
        if kind == 'decimal':
            try:
                if not Decimal(code).is_finite(): raise InvalidOperation()
            except InvalidOperation: raise DefinitionError('숫자형 코드를 입력하세요.') from None
        if kind == 'boolean' and code not in ('true','false'):
            raise DefinitionError('유무형 코드는 true 또는 false입니다.')
        if data.get('id'):
            old = one(cur,'SELECT field_id::text,code FROM gis.definition_code WHERE id=%s',[uid])
            if old != (field,code):
                raise DefinitionError('기존 코드값은 유지하고 표시명·순서만 수정하세요.')
        cur.execute('''INSERT INTO gis.definition_code(id,field_id,code,label,sort_order,enabled)
          VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO UPDATE SET label=EXCLUDED.label,
          sort_order=EXCLUDED.sort_order,enabled=EXCLUDED.enabled''',
          [uid,field,code,text(data.get('label')),number(data.get('sort_order')),boolean(data.get('enabled'),True)])
    elif action == 'field_layer':
        field=identifier(data.get('field')); layer=identifier(data.get('layer'))
        source=one(cur,'SELECT source_layer_id::text FROM gis.definition_field WHERE id=%s',[field])[0]
        if source and source != layer: raise DefinitionError('표준 필드는 원래 레이어에서만 사용합니다.')
        cur.execute('INSERT INTO gis.definition_field_layer VALUES (%s,%s) ON CONFLICT DO NOTHING',[field,layer])
    elif action == 'scope':
        group=identifier(data.get('group')); item=identifier(data.get('catalog')); level=number(data.get('catalog_level'),2)
        _catalog_exists(cur,level,item)
        cur.execute('INSERT INTO gis.definition_group_scope VALUES (%s,%s,%s) ON CONFLICT DO NOTHING',[group,level,item])
    elif action == 'group_layer':
        group=identifier(data.get('group')); layer=identifier(data.get('layer'))
        one(cur,'''SELECT 1 FROM gis.definition_layer l WHERE l.id=%s AND
          (NOT EXISTS(SELECT 1 FROM gis.definition_layer_catalog WHERE layer_id=l.id) OR
           EXISTS(SELECT 1 FROM gis.definition_layer_catalog lc JOIN gis.definition_group_scope s
             ON s.catalog_level=lc.catalog_level AND s.catalog_item_id=lc.catalog_item_id
             WHERE s.group_id=%s AND lc.layer_id=l.id))''',[layer,group],
            '레이어에 해당하는 업무범위를 먼저 등록하세요.')
        cur.execute('INSERT INTO gis.definition_group_layer VALUES (%s,%s) ON CONFLICT DO NOTHING',[group,layer])
    elif action == 'group_field':
        group=identifier(data.get('group')); field=identifier(data.get('field')); layer=identifier(data.get('layer'))
        source=one(cur,'SELECT source_layer_id::text FROM gis.definition_field WHERE id=%s',[field])[0]
        if source and source != layer: raise DefinitionError('다른 레이어의 표준 필드입니다.')
        cur.execute('INSERT INTO gis.definition_field_layer VALUES (%s,%s) ON CONFLICT DO NOTHING',[field,layer])
        cur.execute('''INSERT INTO gis.definition_group_field(group_id,layer_id,field_id,sort_order,required)
          VALUES (%s,%s,%s,%s,%s) ON CONFLICT(group_id,layer_id,field_id) DO UPDATE SET
          sort_order=EXCLUDED.sort_order,required=EXCLUDED.required''',
          [group,layer,field,number(data.get('sort_order')),boolean(data.get('required'))])
    elif action == 'rule':
        source=identifier(data.get('source_field')); target=identifier(data.get('target_field'))
        source_code=identifier(data.get('source_code'))
        selected=data.getlist('allowed') if hasattr(data,'getlist') else data.get('allowed',[])
        allowed=list(dict.fromkeys(identifier(value) for value in selected))
        if not allowed or source == target: raise DefinitionError('서로 다른 필드와 허용값을 하나 이상 선택하세요.')
        _codes_allowed(cur,source); _codes_allowed(cur,target)
        one(cur,'SELECT 1 FROM gis.definition_code WHERE id=%s AND field_id=%s AND enabled',[source_code,source])
        cur.execute('SELECT id FROM gis.definition_code WHERE id=ANY(%s::uuid[]) AND field_id=%s AND enabled',[allowed,target])
        if len(cur.fetchall()) != len(allowed): raise DefinitionError('허용값은 대상 필드의 활성 코드만 선택하세요.')
        cur.execute('''WITH RECURSIVE reach(id) AS (SELECT target_field FROM gis.definition_rule
          WHERE source_field=%s AND id<>%s UNION SELECT r.target_field FROM gis.definition_rule r
          JOIN reach x ON r.source_field=x.id WHERE r.id<>%s) SELECT 1 FROM reach WHERE id=%s''',[target,uid,uid,source])
        if cur.fetchone(): raise DefinitionError('순환하는 필드 조건은 등록할 수 없습니다.')
        cur.execute('DELETE FROM gis.definition_rule_value WHERE rule_id=%s',[uid])
        cur.execute('''INSERT INTO gis.definition_rule VALUES (%s,%s,%s,%s) ON CONFLICT(id) DO UPDATE SET
          source_field=EXCLUDED.source_field,source_code=EXCLUDED.source_code,target_field=EXCLUDED.target_field''',[uid,source,source_code,target])
        for value in allowed: cur.execute('INSERT INTO gis.definition_rule_value VALUES (%s,%s,%s)',[uid,target,value])
    elif action == 'delete_rule':
        cur.execute('DELETE FROM gis.definition_rule_value WHERE rule_id=%s',[uid]); cur.execute('DELETE FROM gis.definition_rule WHERE id=%s',[uid])
    elif action == 'delete_code': cur.execute('DELETE FROM gis.definition_code WHERE id=%s',[uid])
    elif action == 'delete_field':
        one(cur,'SELECT 1 FROM gis.definition_field WHERE id=%s AND source_layer_id IS NULL',[uid],'기존 표준 필드는 삭제할 수 없습니다.')
        cur.execute('UPDATE gis.definition_field SET active=false,updated_at=now() WHERE id=%s',[uid])
    elif action == 'delete_group':
        cur.execute('SELECT count(*) FROM gis.definition_group_layer WHERE group_id=%s',[uid])
        layer_count=int(cur.fetchone()[0])
        if layer_count:
            raise DefinitionError(f'이 그룹에는 {layer_count}개의 레이어가 있습니다. 다른 그룹 또는 미분류로 이동한 후 삭제하세요.')
        cur.execute('DELETE FROM gis.definition_group_scope WHERE group_id=%s',[uid])
        cur.execute('DELETE FROM gis.definition_group WHERE id=%s',[uid])
    elif action == 'delete_scope':
        cur.execute('DELETE FROM gis.definition_group_scope WHERE group_id=%s AND catalog_level=%s AND catalog_item_id=%s',
                    [identifier(data.get('group')),number(data.get('catalog_level'),2),identifier(data.get('catalog'))])
    elif action == 'delete_group_layer':
        cur.execute('DELETE FROM gis.definition_group_layer WHERE group_id=%s AND layer_id=%s',[identifier(data.get('group')),identifier(data.get('layer'))])
    elif action == 'delete_group_field':
        cur.execute('DELETE FROM gis.definition_group_field WHERE group_id=%s AND layer_id=%s AND field_id=%s',
                    [identifier(data.get('group')),identifier(data.get('layer')),identifier(data.get('field'))])
    elif action == 'delete_field_layer':
        cur.execute('DELETE FROM gis.definition_field_layer WHERE field_id=%s AND layer_id=%s',[identifier(data.get('field')),identifier(data.get('layer'))])
    return uid


def snapshot(cur):
    data = {
      'groups':rows(cur,'SELECT id::text,name FROM gis.definition_group ORDER BY name'),
      'layer_groups':rows(cur,'''SELECT id::text,group_code,group_name,display_name,sort_order,active,description
        FROM gis.definition_layer_group ORDER BY sort_order,display_name,group_code'''),
      'layers':rows(cur,'''SELECT id::text,standard_name,physical_name,label,domain_code,geometry_kind,
        feature_role,scope_type,sort_order,active,layer_group_id::text,description,updated_at
        FROM gis.definition_layer ORDER BY sort_order,standard_name'''),
      'catalogs':rows(cur,"SELECT id::text,code,name FROM catalog.category_node WHERE level=2 AND active ORDER BY ord,code"),
      'layer_catalogs':rows(cur,'''SELECT lc.layer_id::text,l.standard_name AS layer_name,lc.catalog_level,
        lc.catalog_item_id::text AS catalog_id,lc.catalog_item_id::text FROM gis.definition_layer_catalog lc
        JOIN gis.definition_layer l ON l.id=lc.layer_id ORDER BY l.standard_name,lc.catalog_level,lc.catalog_item_id'''),
      'fields':rows(cur,'''SELECT f.id::text,f.source_layer_id::text,l.standard_name AS source_layer,
        f.physical_name,f.standard_name,f.label,f.storage_data_type,f.storage_udt_name,f.kind,f.widget_type,
        f.max_length,f.precision,f.scale,f.nullable,f.storage_default,f.visible,f.form_visible,f.table_visible,f.required,f.readonly,
        f.default_value,f.sort_order,f.unit,f.description,f.layout,f.active,f.updated_at,
        (SELECT count(*) FROM gis.definition_code c WHERE c.field_id=f.id AND c.enabled) AS code_count
        FROM gis.definition_field f LEFT JOIN gis.definition_layer l ON l.id=f.source_layer_id
        ORDER BY COALESCE(l.sort_order,2147483647),f.sort_order,f.label'''),
      'field_layers':rows(cur,'''SELECT fl.field_id::text,fl.layer_id::text,l.standard_name AS layer_name
        FROM gis.definition_field_layer fl JOIN gis.definition_layer l ON l.id=fl.layer_id'''),
      'codes':rows(cur,'''SELECT id::text,field_id::text,code,label,sort_order,enabled
        FROM gis.definition_code ORDER BY field_id,sort_order,code'''),
      'scopes':rows(cur,'''SELECT group_id::text,catalog_level,catalog_item_id::text AS catalog_id,
        catalog_item_id::text FROM gis.definition_group_scope'''),
      'group_layers':rows(cur,'''SELECT gl.group_id::text,gl.layer_id::text,l.standard_name AS layer_name
        FROM gis.definition_group_layer gl JOIN gis.definition_layer l ON l.id=gl.layer_id'''),
      'group_fields':rows(cur,'''SELECT gf.group_id::text,gf.layer_id::text,l.standard_name AS layer_name,
        gf.field_id::text,gf.sort_order,gf.required,gf.visible,gf.readonly,gf.layout
        FROM gis.definition_group_field gf JOIN gis.definition_layer l ON l.id=gf.layer_id'''),
      'rules':rows(cur,'''SELECT r.id::text,r.source_field::text,r.source_code::text,r.target_field::text,
        COALESCE(array_agg(v.code_id::text ORDER BY c.sort_order,c.code) FILTER(WHERE v.code_id IS NOT NULL),'{}') AS allowed
        FROM gis.definition_rule r LEFT JOIN gis.definition_rule_value v ON v.rule_id=r.id
        LEFT JOIN gis.definition_code c ON c.id=v.code_id GROUP BY r.id ORDER BY r.id'''),
      'kinds':KINDS,'widgets':WIDGETS,
    }
    revision_source={key:data[key] for key in (
        'groups','layer_groups','layers','layer_catalogs','fields','field_layers','codes',
        'scopes','group_layers','group_fields','rules'
    )}
    data['definition_revision']=hashlib.sha256(
        json.dumps(revision_source,sort_keys=True,ensure_ascii=False,default=str,
                   separators=(',',':')).encode()
    ).hexdigest()
    return data
