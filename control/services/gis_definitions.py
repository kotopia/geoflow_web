"""Central GIS authoring. Connections/authorization belong to callers; no tenant writes."""
from uuid import uuid4
from geoflow_ops.gis.form_definitions import DefinitionError, identifier, text, rows

KINDS = {'text':'문자', 'integer':'정수', 'decimal':'소수', 'boolean':'유무',
         'date':'날짜', 'photo':'사진', 'relation':'관계형'}


def ready(cur):
    cur.execute("SELECT to_regclass('gis.definition_rule_value') IS NOT NULL")
    return bool(cur.fetchone()[0])


def number(value, default=0):
    try:
        n = int(value if value not in (None, '') else default)
    except (TypeError, ValueError):
        raise DefinitionError('숫자 입력을 확인하세요.') from None
    if not -2147483648 <= n <= 2147483647:
        raise DefinitionError('숫자 범위를 확인하세요.')
    return n


def field_values(data):
    kind = data.get('kind')
    if kind not in KINDS:
        raise DefinitionError('필드 유형을 선택하세요.')
    length = number(data.get('max_length'),255) if kind=='text' else None
    precision = number(data.get('precision'),12) if kind=='decimal' else None
    scale = number(data.get('scale'),2) if kind=='decimal' else None
    if length is not None and not 1 <= length <= 100000:
        raise DefinitionError('문자 길이는 1~100000입니다.')
    if precision is not None and not 0 <= scale <= precision <= 38 or precision == 0:
        raise DefinitionError('전체 자릿수는 1~38, 소수 자릿수는 전체 자릿수 이하입니다.')
    return [text(data.get('label')),kind,length,precision,scale,number(data.get('sort_order'))]


def one(cur, sql, params, message='대상을 찾을 수 없습니다.'):
    cur.execute(sql,params)
    result=cur.fetchone()
    if not result:
        raise DefinitionError(message)
    return result


def _codes_allowed(cur, field):
    kind=one(cur,'SELECT kind FROM gis.definition_field WHERE id=%s',[field])[0]
    if kind not in ('text','integer','decimal','boolean'):
        raise DefinitionError('이 유형에는 참조코드를 연결할 수 없습니다.')
    return kind


def mutate(cur,data):
    action=data.get('action','')
    actions={'group','field','code','scope','group_layer','group_field','field_layer','rule',
             'delete_group','delete_field','delete_code','delete_scope','delete_group_layer',
             'delete_group_field','delete_field_layer','delete_rule'}
    if action not in actions:
        raise DefinitionError('지원하지 않는 요청입니다.')
    # Serializes authoring/deletion and protects read-before-write validations.
    cur.execute("SELECT pg_advisory_xact_lock(hashtext('geoflow.central.gis.definitions'))")
    uid=identifier(data['id']) if data.get('id') else str(uuid4())
    if action=='group':
        cur.execute('INSERT INTO gis.definition_group VALUES (%s,%s) ON CONFLICT(id) DO UPDATE SET name=EXCLUDED.name',[uid,text(data.get('label'))])
    elif action=='field':
        values=field_values(data)
        if data.get('id'):
            old=one(cur,'SELECT kind,source_layer FROM gis.definition_field WHERE id=%s',[uid])
            if old[1]:
                raise DefinitionError('표준 필드 구조는 이 화면에서 변경할 수 없습니다.')
            if old[0]!=values[1]:
                cur.execute('SELECT 1 FROM gis.definition_code WHERE field_id=%s LIMIT 1',[uid])
                if cur.fetchone():
                    raise DefinitionError('참조코드를 먼저 정리한 후 유형을 변경하세요.')
        cur.execute('''INSERT INTO gis.definition_field(id,label,kind,max_length,precision,scale,sort_order)
            VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO UPDATE SET label=EXCLUDED.label,
            kind=EXCLUDED.kind,max_length=EXCLUDED.max_length,precision=EXCLUDED.precision,
            scale=EXCLUDED.scale,sort_order=EXCLUDED.sort_order''',[uid,*values])
    elif action=='code':
        field=identifier(data.get('field'))
        kind=_codes_allowed(cur,field)
        code=text(data.get('code'))
        if kind=='integer':
            try: int(code)
            except ValueError: raise DefinitionError('정수형 코드를 입력하세요.') from None
        if kind=='decimal':
            from decimal import Decimal, InvalidOperation
            try:
                if not Decimal(code).is_finite(): raise InvalidOperation()
            except InvalidOperation: raise DefinitionError('숫자형 코드를 입력하세요.') from None
        if kind=='boolean' and code not in ('true','false'):
            raise DefinitionError('유무형 코드는 true 또는 false입니다.')
        if data.get('id'):
            old=one(cur,'SELECT field_id::text,code FROM gis.definition_code WHERE id=%s',[uid])
            if old[0]!=field or old[1]!=code:
                raise DefinitionError('기존 코드값은 유지하고 표시명·순서를 수정하세요. 값 변경은 삭제 후 등록하세요.')
        cur.execute('''INSERT INTO gis.definition_code VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT(id) DO UPDATE SET label=EXCLUDED.label,sort_order=EXCLUDED.sort_order''',
            [uid,field,code,text(data.get('label')),number(data.get('sort_order'))])
    elif action=='field_layer':
        field=identifier(data.get('field')); layer=text(data.get('layer'))
        source=one(cur,'SELECT source_layer FROM gis.definition_field WHERE id=%s',[field])[0]
        if source and source!=layer:
            raise DefinitionError('표준 필드는 원래 레이어에서만 사용합니다.')
        cur.execute('INSERT INTO gis.definition_field_layer VALUES (%s,%s) ON CONFLICT DO NOTHING',[field,layer])
    elif action=='scope':
        group=identifier(data.get('group')); catalog=identifier(data.get('catalog'))
        one(cur,'SELECT 1 FROM catalog.category_node WHERE id=%s AND active AND level=2',[catalog])
        cur.execute('INSERT INTO gis.definition_group_scope VALUES (%s,%s) ON CONFLICT DO NOTHING',[group,catalog])
    elif action=='group_layer':
        group=identifier(data.get('group')); layer=text(data.get('layer'))
        one(cur,'''SELECT 1 FROM gis.definition_layer l WHERE l.standard_name=%s AND
          (NOT EXISTS(SELECT 1 FROM gis.definition_layer_catalog WHERE layer_name=l.standard_name)
           OR EXISTS(SELECT 1 FROM gis.definition_layer_catalog lc JOIN gis.definition_group_scope s
            ON s.catalog_id=lc.catalog_id WHERE s.group_id=%s AND lc.layer_name=l.standard_name))''',[layer,group],
            '레이어에 해당하는 업무범위를 먼저 등록하세요.')
        cur.execute('INSERT INTO gis.definition_group_layer VALUES (%s,%s) ON CONFLICT DO NOTHING',[group,layer])
    elif action=='group_field':
        group=identifier(data.get('group')); field=identifier(data.get('field')); layer=text(data.get('layer'))
        source=one(cur,'SELECT source_layer FROM gis.definition_field WHERE id=%s',[field])[0]
        if source and source!=layer:
            raise DefinitionError('다른 레이어의 표준 필드입니다.')
        cur.execute('INSERT INTO gis.definition_field_layer VALUES (%s,%s) ON CONFLICT DO NOTHING',[field,layer])
        cur.execute('''INSERT INTO gis.definition_group_field VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT(group_id,layer_name,field_id) DO UPDATE SET sort_order=EXCLUDED.sort_order,required=EXCLUDED.required''',
            [group,layer,field,number(data.get('sort_order')),data.get('required')=='true'])
    elif action=='rule':
        source=identifier(data.get('source_field')); target=identifier(data.get('target_field'))
        source_code=identifier(data.get('source_code'))
        selected=data.getlist('allowed') if hasattr(data,'getlist') else data.get('allowed',[])
        allowed=list(dict.fromkeys(identifier(v) for v in selected))
        if not allowed or source==target:
            raise DefinitionError('서로 다른 필드와 허용값을 하나 이상 선택하세요.')
        _codes_allowed(cur,source); _codes_allowed(cur,target)
        one(cur,'SELECT 1 FROM gis.definition_code WHERE id=%s AND field_id=%s',[source_code,source])
        cur.execute('SELECT id FROM gis.definition_code WHERE id=ANY(%s::uuid[]) AND field_id=%s',[allowed,target])
        if len(cur.fetchall())!=len(allowed):
            raise DefinitionError('허용값은 대상 필드의 코드만 선택하세요.')
        # Reject cycles, including multi-hop dependencies.
        cur.execute('''WITH RECURSIVE reach(id) AS (SELECT target_field FROM gis.definition_rule
            WHERE source_field=%s AND id<>%s UNION SELECT r.target_field FROM gis.definition_rule r
            JOIN reach x ON r.source_field=x.id WHERE r.id<>%s) SELECT 1 FROM reach WHERE id=%s''',
            [target,uid,uid,source])
        if cur.fetchone(): raise DefinitionError('순환하는 필드 조건은 등록할 수 없습니다.')
        cur.execute('DELETE FROM gis.definition_rule_value WHERE rule_id=%s',[uid])
        cur.execute('''INSERT INTO gis.definition_rule VALUES (%s,%s,%s,%s) ON CONFLICT(id)
            DO UPDATE SET source_field=EXCLUDED.source_field,source_code=EXCLUDED.source_code,target_field=EXCLUDED.target_field''',
            [uid,source,source_code,target])
        for value in allowed:
            cur.execute('INSERT INTO gis.definition_rule_value VALUES (%s,%s,%s)',[uid,target,value])
    elif action=='delete_rule':
        cur.execute('DELETE FROM gis.definition_rule_value WHERE rule_id=%s',[uid])
        cur.execute('DELETE FROM gis.definition_rule WHERE id=%s',[uid])
    elif action=='delete_code':
        # FK restrictions preserve condition rules; codes can be removed explicitly.
        cur.execute('DELETE FROM gis.definition_code WHERE id=%s',[uid])
    elif action=='delete_field':
        one(cur,'SELECT 1 FROM gis.definition_field WHERE id=%s AND source_layer IS NULL',[uid],
            '기존 표준 필드는 삭제할 수 없습니다.')
        cur.execute('DELETE FROM gis.definition_field WHERE id=%s',[uid])
    elif action=='delete_group':
        # Linked scopes/layers must be intentionally removed first.
        cur.execute('DELETE FROM gis.definition_group WHERE id=%s',[uid])
    elif action=='delete_scope':
        group=identifier(data.get('group')); catalog=identifier(data.get('catalog'))
        cur.execute('''SELECT 1 FROM gis.definition_group_layer gl JOIN gis.definition_layer_catalog lc
            ON lc.layer_name=gl.layer_name WHERE gl.group_id=%s AND lc.catalog_id=%s LIMIT 1''',[group,catalog])
        if cur.fetchone(): raise DefinitionError('연결된 레이어를 먼저 제거하세요.')
        cur.execute('DELETE FROM gis.definition_group_scope WHERE group_id=%s AND catalog_id=%s',[group,catalog])
    elif action=='delete_group_layer':
        cur.execute('DELETE FROM gis.definition_group_layer WHERE group_id=%s AND layer_name=%s',
                    [identifier(data.get('group')),text(data.get('layer'))])
    elif action=='delete_group_field':
        cur.execute('DELETE FROM gis.definition_group_field WHERE group_id=%s AND layer_name=%s AND field_id=%s',
                    [identifier(data.get('group')),text(data.get('layer')),identifier(data.get('field'))])
    elif action=='delete_field_layer':
        field=identifier(data.get('field')); layer=text(data.get('layer'))
        one(cur,'SELECT 1 FROM gis.definition_field WHERE id=%s AND source_layer IS NULL',[field])
        cur.execute('SELECT 1 FROM gis.definition_group_field WHERE field_id=%s AND layer_name=%s',[field,layer])
        if cur.fetchone(): raise DefinitionError('그룹에서 사용 중인 연결입니다.')
        cur.execute('DELETE FROM gis.definition_field_layer WHERE field_id=%s AND layer_name=%s',[field,layer])
    return uid


def snapshot(cur):
    return {
        'groups':rows(cur,'SELECT id::text,name FROM gis.definition_group ORDER BY name'),
        'catalogs':rows(cur,'SELECT id::text,name,code FROM catalog.category_node WHERE active AND level=2 ORDER BY ord,name'),
        'layers':rows(cur,'SELECT standard_name,label FROM gis.definition_layer ORDER BY label,standard_name'),
        'layer_catalogs':rows(cur,'SELECT layer_name,catalog_id::text FROM gis.definition_layer_catalog'),
        'fields':rows(cur,'''SELECT f.id::text,f.label,f.kind,f.max_length,f.precision,f.scale,f.sort_order,
            f.source_layer,f.physical_name,(SELECT count(*) FROM gis.definition_code c WHERE c.field_id=f.id) AS code_count
            FROM gis.definition_field f ORDER BY f.sort_order,f.label,f.id'''),
        'field_layers':rows(cur,'SELECT field_id::text,layer_name FROM gis.definition_field_layer'),
        'codes':rows(cur,'SELECT id::text,field_id::text,code,label,sort_order FROM gis.definition_code ORDER BY sort_order,code'),
        'scopes':rows(cur,'SELECT group_id::text,catalog_id::text FROM gis.definition_group_scope'),
        'group_layers':rows(cur,'SELECT group_id::text,layer_name FROM gis.definition_group_layer'),
        'group_fields':rows(cur,'SELECT group_id::text,layer_name,field_id::text,sort_order,required FROM gis.definition_group_field ORDER BY sort_order,field_id'),
        'rules':rows(cur,'''SELECT r.id::text,r.source_field::text,r.source_code::text,r.target_field::text,
            array_agg(v.code_id::text ORDER BY v.code_id) AS allowed FROM gis.definition_rule r
            JOIN gis.definition_rule_value v ON v.rule_id=r.id GROUP BY r.id ORDER BY r.id'''),
        'kinds':KINDS,
    }
