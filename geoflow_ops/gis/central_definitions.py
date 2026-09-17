"""Resolve central GIS definitions after tenant/project authorization."""
from __future__ import annotations

import hashlib
import json

from django.db import connections

from control.services import gis_definitions as central
from .form_definitions import DefinitionError


def central_snapshot():
    with connections['default'].cursor() as cur:
        if not central.ready(cur):
            return None
        return central.snapshot(cur)


def project_config(cur, project_id):
    empty = {'group_id':None,'additions':{},'private_items':{},'overrides':{},'definition_revision':None}
    cur.execute("SELECT to_regclass('gis.project_definition')")
    if not cur.fetchone()[0]:
        return empty
    cur.execute('''SELECT group_id::text,additions,private_items,overrides,definition_revision
        FROM gis.project_definition WHERE project_id=%s''',[str(project_id)])
    row = cur.fetchone()
    config = dict(zip(empty, row)) if row else empty.copy()
    for key in ('additions','private_items','overrides'):
        value = config[key]
        if isinstance(value,str):
            try: value=json.loads(value)
            except (ValueError,TypeError): raise DefinitionError('프로젝트 구성 JSON이 올바르지 않습니다.') from None
        if not isinstance(value,dict): raise DefinitionError('프로젝트 구성은 항목별 객체여야 합니다.')
        config[key]=value
    if any(not isinstance(value,list) or any(not isinstance(item,str) for item in value)
           for value in config['additions'].values()):
        raise DefinitionError('프로젝트 추가 항목의 레이어 목록이 올바르지 않습니다.')
    return config


def _revision(payload):
    return hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False,default=str,
                                     separators=(',',':')).encode()).hexdigest()


def resolve(data, config, layers, *, include_unavailable=False):
    """Return one normalized definition for standard and additional fields."""
    available={str(layer['id']):layer for layer in layers}
    selected=dict(available)
    if include_unavailable:
        selected.update({layer['id']:layer for layer in data['layers'] if layer['id'] not in selected})
    all_layers={layer['id']:layer for layer in data['layers']}
    fields={field['id']:field for field in data['fields']}
    groups={group['id']:group for group in data['groups']}
    group_id=config.get('group_id')
    if group_id and group_id not in groups:
        raise DefinitionError('선택한 업무 그룹이 삭제되었습니다. 그룹을 다시 선택하세요.')

    # Every standard physical field belongs to the base form. Group/project links
    # add central extension fields or override order/flags; they never duplicate it.
    links={}
    for field in fields.values():
        layer_id=field.get('source_layer_id')
        if layer_id in selected:
            links[(field['id'],layer_id)]={'sort_order':field['sort_order'],'required':field['required'],
                'visible':field['visible'],'readonly':field['readonly'],'layout':field.get('layout') or {},
                'source':'standard','inherited':False}
    for link in data['group_fields']:
        if link['group_id'] != group_id or link['layer_id'] not in selected:
            continue
        base=fields.get(link['field_id'])
        if not base: continue
        links[(link['field_id'],link['layer_id'])]={'sort_order':link['sort_order'],
            'required':link['required'],'visible':base['visible'] if link['visible'] is None else link['visible'],
            'readonly':base['readonly'] if link['readonly'] is None else link['readonly'],
            'layout':link.get('layout') or base.get('layout') or {},'source':'group','inherited':True}
    for field_id, layer_ids in config.get('additions',{}).items():
        field=fields.get(field_id)
        if not field: continue
        for layer_id in layer_ids:
            if layer_id in selected:
                links.setdefault((field_id,layer_id),{'sort_order':field['sort_order'],'required':field['required'],
                    'visible':field['visible'],'readonly':field['readonly'],'layout':field.get('layout') or {},
                    'source':'project','inherited':False})
    private=dict(config.get('private_items',{}))
    fields.update(private)
    for field_id,field in private.items():
        layer_id=field.get('source_layer_id')
        if layer_id in selected:
            links[(field_id,layer_id)]={'sort_order':field.get('sort_order',0),'required':field.get('required',False),
                'visible':field.get('visible',True),'readonly':field.get('readonly',False),
                'layout':field.get('layout') or {},'source':'project','inherited':False}

    overrides=config.get('overrides',{})
    result_fields=[]
    for (field_id,layer_id),link in links.items():
        field=fields[field_id]; layer=all_layers.get(layer_id,selected[layer_id])
        override=overrides.get(field_id,{}) if isinstance(overrides.get(field_id,{}),dict) else {}
        semantic=field.get('kind','text')
        storage = ({'kind':'column','key':field['physical_name']} if field.get('physical_name') else
                   {'kind':'ops.attachments','purpose':'gis_form:'+field_id} if semantic=='photo' else
                   {'kind':'relation','definition_only':True} if semantic=='relation' else
                   {'kind':'ext_data','namespace':'gis_form','key':field_id})
        entry={
            'id':field_id,'source':link['source'],'layer_id':layer_id,
            'layer_standard_name':layer['standard_name'],'field_name':field.get('physical_name'),
            'field_identifier':field.get('standard_name') or field_id,'label':override.get('label',field['label']),
            'storage_data_type':field.get('storage_data_type'),'semantic_data_type':semantic,
            'widget_type':override.get('widget_type',field.get('widget_type','text')),
            'visible':override.get('visible',link['visible']),
            'required':override.get('required',link['required']),
            'readonly':override.get('readonly',link['readonly']),
            'default':override.get('default',field.get('default_value')),
            'display_order':override.get('display_order',link['sort_order']),
            'layout':override.get('layout',link['layout']),
            'max_length':field.get('max_length'),'precision':field.get('precision'),'scale':field.get('scale'),
            'nullable':field.get('nullable',True),'unit':field.get('unit',''),
            'description':field.get('description',''),'storage':storage,
            'layer_available':layer_id in available,'inherited':link['inherited'],
        }
        result_fields.append(entry)
    result_fields.sort(key=lambda value:(value['layer_standard_name'],value['display_order'],value['label'],value['id']))

    included={field['id'] for field in result_fields}
    code_map={field_id:[] for field_id in included}
    for code in data['codes']:
        if code['field_id'] in included:
            code_map[code['field_id']].append({'id':code['id'],'value':code['code'],'label':code['label'],
                                               'order':code['sort_order'],'enabled':code['enabled']})
    for field in result_fields:
        field['reference_codes']=code_map.get(field['id'],[])
    rules=[]
    for rule in data['rules']:
        if rule['source_field'] in included and rule['target_field'] in included:
            rules.append({'id':rule['id'],'source_field_id':rule['source_field'],
                'source_code_id':rule['source_code'],'target_field_id':rule['target_field'],
                'allowed_code_ids':rule['allowed']})
    payload={'version':'gis-final-form-v3','group':groups.get(group_id),'fields':result_fields,
             'rules':rules,'components':[]}
    payload['revision']=_revision(payload)
    # Existing web template reads items; this is the same resolved collection,
    # not a second definition store.
    payload['items']=payload['fields']
    return payload


def reference_payload(data, layer_ids):
    ids=set(layer_ids)
    fields=[field for field in data['fields'] if field.get('source_layer_id') in ids and field.get('physical_name')]
    bindings=[]; groups=[]
    layers={layer['id']:layer for layer in data['layers']}
    for field in fields:
        values=[{'id':code['id'],'code':code['code'],'label':code['label'],
                 'sort_order':code['sort_order'],'enabled':code['enabled']}
                for code in data['codes'] if code['field_id']==field['id']]
        if not values: continue
        key='central:'+field['id']; layer=layers[field['source_layer_id']]
        bindings.append({'layer_id':field['source_layer_id'],'standard_name':layer['standard_name'],
            'field_id':field['id'],'field_standard_name':field.get('standard_name') or field['physical_name'].upper(),
            'field_name':field['physical_name'],'field_label':field['label'],'code_group_key':key})
        groups.append({'code_group_key':key,'field_id':field['id'],'name':field['label'],'values':values})
    field_ids={field['id'] for field in fields}
    rules=[{'id':rule['id'],'source_field_id':rule['source_field'],'source_code_id':rule['source_code'],
            'target_field_id':rule['target_field'],'allowed_code_ids':rule['allowed']}
           for rule in data['rules'] if rule['source_field'] in field_ids and rule['target_field'] in field_ids]
    return {'ok':True,'version':'gis-reference-v2','reference_store':'central.gis.definition_code',
            'runtime_source':'central.gis','bindings':bindings,'groups':groups,
            'binding_count':len(bindings),'group_count':len(groups),'rules':rules}


def validate_attributes(plan,standard_name,attrs):
    """Apply the same central required/code/conditional rules on server writes."""
    definition=plan.get('form_definition') or {}
    fields=[field for field in definition.get('fields',[])
            if str(field.get('layer_standard_name')).upper()==str(standard_name).upper()]
    if not fields: raise DefinitionError('레이어 Form Definition을 찾을 수 없습니다.')
    extension=attrs.get('ext_data') or {}
    if isinstance(extension,str):
        try: extension=json.loads(extension)
        except (TypeError,ValueError): raise DefinitionError('확장 필드 JSON이 올바르지 않습니다.') from None
    extension=(extension.get('gis_form') or {}) if isinstance(extension,dict) else {}
    values={}
    for field in fields:
        storage=field.get('storage') or {}
        value=(attrs.get(storage.get('key')) if storage.get('kind')=='column'
               else extension.get(field['id']) if storage.get('kind')=='ext_data' else None)
        values[field['id']]=value
        if field.get('required') and field.get('visible') and value in (None,''):
            raise DefinitionError(field['label']+' 필드는 필수입니다.')
        codes=[code for code in field.get('reference_codes',[]) if code.get('enabled')]
        if codes and value not in (None,'') and str(value) not in {str(code['value']) for code in codes}:
            raise DefinitionError(field['label']+' 코드값이 중앙 정의와 일치하지 않습니다.')
    by_id={field['id']:field for field in fields}
    for rule in definition.get('rules',[]):
        source=by_id.get(rule['source_field_id']); target=by_id.get(rule['target_field_id'])
        if not source or not target: continue
        source_code=next((code for code in source.get('reference_codes',[])
                          if code.get('enabled') and str(code['value'])==str(values.get(source['id']))),None)
        if not source_code or source_code['id']!=rule['source_code_id']: continue
        target_value=values.get(target['id'])
        if target_value in (None,''): continue
        target_code=next((code for code in target.get('reference_codes',[])
                          if code.get('enabled') and str(code['value'])==str(target_value)),None)
        if not target_code or target_code['id'] not in set(rule['allowed_code_ids']):
            raise DefinitionError(target['label']+' 값이 연결 규칙에서 허용되지 않습니다.')
