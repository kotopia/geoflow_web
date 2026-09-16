"""Read central definitions only after callers establish tenant/project authorization."""
import hashlib
import json
from django.db import connections
from control.services import gis_definitions as central
from .form_definitions import DefinitionError, identifier


def central_snapshot():
    with connections['default'].cursor() as cur:
        if not central.ready(cur): return None
        return central.snapshot(cur)


def project_config(cur, project_id):
    cur.execute("SELECT to_regclass('gis.project_definition')")
    if not cur.fetchone()[0]: return {'group_id':None,'additions':{},'private_items':{}}
    cur.execute('SELECT group_id::text,additions,private_items FROM gis.project_definition WHERE project_id=%s',[str(project_id)])
    r=cur.fetchone()
    return dict(zip(('group_id','additions','private_items'),r)) if r else {'group_id':None,'additions':{},'private_items':{}}


def resolve(data, config, layers):
    """Intersect central group definitions with the authoritative tenant Layer Plan."""
    names={str(l['standard_name']).upper():str(l['id']) for l in layers}
    fields={f['id']:f for f in data['fields']}
    groups={g['id']:g for g in data['groups']}
    group=config.get('group_id')
    if group and group not in groups:
        raise DefinitionError('선택한 업무 그룹이 삭제되었습니다. 그룹을 다시 선택하세요.')
    links={}
    for link in data['group_fields']:
        if link['group_id']==group and link['layer_name'] in names:
            links[(link['field_id'],link['layer_name'])]={**link,'inherited':True}
    for fid, layer_names in config.get('additions',{}).items():
        if fid not in fields: continue
        for name in layer_names:
            if name in names: links.setdefault((fid,name),{'field_id':fid,'layer_name':name,'sort_order':fields[fid]['sort_order'],'required':False,'inherited':False})
    fields.update(config.get('private_items',{}))
    for fid,f in config.get('private_items',{}).items():
        name=f['source_layer']
        if name in names: links[(fid,name)]={'field_id':fid,'layer_name':name,'sort_order':f['sort_order'],'required':False,'inherited':False}
    items=[]
    for (fid,name), link in links.items():
        f=fields[fid]
        if f.get('physical_name') and f['source_layer']!=name: continue
        kind=f['kind']; key='central:'+fid
        items.append({**f,'feature_type_id':names[name],'standard_name':name,
            'kind':'photo' if kind=='photo' else 'relation' if kind=='relation' else 'scalar',
            'config':{'data_type':kind,'max_length':f.get('max_length'),'precision':f.get('precision'),'scale':f.get('scale')},
            'sort_order':link['sort_order'],'inherited':link['inherited'],
            'source':'group' if link['inherited'] else 'project','required_display':link['inherited'],
            'required_on_complete':link['required'],'code_group_key':key,
            'storage':{'kind':'column','key':f['physical_name']} if f.get('physical_name') else
                      {'kind':'ops.attachments','purpose':'gis_form:'+fid} if kind=='photo' else
                      {'kind':'relation','definition_only':True} if kind=='relation' else
                      {'kind':'ext_data','namespace':'gis_form','key':fid}})
    items.sort(key=lambda x:(x['standard_name'],x['sort_order'],x['label'],x['id']))
    ids={x['id'] for x in items}
    values={fid:[] for fid in ids}
    for c in data['codes']:
        if c['field_id'] in ids: values[c['field_id']].append({k:c[k] for k in ('code','label','sort_order')})
    refs=[{'code_group_key':'central:'+fid,'name':fields[fid]['label'],'values':v} for fid,v in sorted(values.items()) if v]
    rules=[r for r in data['rules'] if r['source_field'] in ids and r['target_field'] in ids]
    result={'version':'gis-form-v2','items':items,'groups':refs,'rules':rules,'group':groups.get(group),
            'client_integration_required':True}
    result['revision']=hashlib.sha256(json.dumps(result,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
    return result


def reference_payload(data, names):
    """Preserves the reference-v1 wire shape for existing QGIS/QField consumers."""
    names=set(names)
    fs=[f for f in data['fields'] if f['source_layer'] in names and f['physical_name']]
    bindings=[]; groups=[]
    for f in fs:
        values=[{k:c[k] for k in ('code','label','sort_order')} for c in data['codes'] if c['field_id']==f['id']]
        if not values: continue
        key='central:'+f['id']
        bindings.append({'standard_name':f['source_layer'],'field_standard_name':f['physical_name'].upper(),
                         'field_name':f['physical_name'],'field_label':f['label'],'code_group_key':key})
        groups.append({'code_group_key':key,'name':f['label'],'values':values})
    ids={f['id'] for f in fs}
    return {'ok':True,'version':'gis-reference-v1','reference_store':'central.gis.definition_code',
            'runtime_source':'central.gis','bindings':bindings,'groups':groups,
            'binding_count':len(bindings),'group_count':len(groups),
            'rules':[r for r in data['rules'] if r['source_field'] in ids and r['target_field'] in ids]}
