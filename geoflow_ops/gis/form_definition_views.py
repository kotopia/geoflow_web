import json
import logging
from uuid import uuid4
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import connections, transaction, DatabaseError
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_GET, require_http_methods
from . import form_definitions as definitions
from . import central_definitions as central
from .reference_groups import selected_group_ids, scope_layers
from .layer_plan import _project_scopes
from control.services.gis_definitions import field_values
from .views import _require_gis_view, _require_project_gis_access
from .qgis_views import _require_qgis_context, _require_project
from .photo_policy_views import central_photo_snapshot, _paired_scopes
from control.services import gis_photo_policy
from geoflow_ops.services.project_access import project_access_policy

logger=logging.getLogger(__name__)


@login_required
@require_GET
def definition_api(request, project_id):
    alias=_require_qgis_context(request)
    _project,_policy,plan=_require_project(request,alias,project_id)
    payload=plan.get('form_definition')
    if payload is None:
        return JsonResponse({'ok':False,'error':'form_definition_schema_pending'},status=503)
    response=JsonResponse({'ok':True,**payload})
    response['Cache-Control']='private, no-store'
    return response


@login_required
@require_http_methods(['GET','POST'])
def project_configuration(request,project_id):
    alias=_require_gis_view(request)
    project,plan=_require_project_gis_access(request,alias,project_id,allow_unready=True,allow_disabled=True)
    can_edit=project_access_policy(request,alias).can_edit_project(project.id)
    if request.method=='POST' and not can_edit: raise PermissionDenied('프로젝트 설정 권한이 없습니다.')
    context={'project':project,'plan':plan,'can_edit':can_edit,'features':plan['layers']}
    try:
        with transaction.atomic(using='default'):
            if request.method == 'POST' and request.POST.get('action') == 'reference_groups':
                with connections['default'].cursor() as lock_cur:
                    lock_cur.execute("SELECT pg_advisory_xact_lock(hashtext('geoflow.central.gis.definitions'))")
            data=central.central_snapshot()
            context['ready']=data is not None
            if data is None: raise definitions.DefinitionError('중앙 업무정의 구조 적용 전입니다.')
            layer_ids={l['id'] for l in data['layers']}
            context['features']=data['layers']
            context['groups']=data['groups']
            context['available']=[f for f in data['fields'] if not f['source_layer_id'] or f['source_layer_id'] in layer_ids]
            with transaction.atomic(using=alias),connections[alias].cursor() as cur:
                cur.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',['gis.definition.project:'+str(project_id)])
                config=central.project_config(cur,project_id)
                scopes = _project_scopes(alias, project_id)
                config['reference_scope_layers'] = scope_layers(data, scopes)
                if request.method=='POST':
                    cur.execute("SELECT to_regclass('gis.project_definition')")
                    if not cur.fetchone()[0]: raise definitions.DefinitionError('프로젝트 구성 저장 구조 적용 전입니다.')
                    action=request.POST.get('action')
                    if action=='reference_groups':
                        if not data.get('reference_groups_ready') or not config.get('reference_groups_ready'):
                            raise definitions.DefinitionError('중앙 및 Tenant 적용그룹 migration 적용 전입니다.')
                        l2 = definitions.identifier(request.POST.get('catalog_l2'))
                        if l2 not in ({row.get('2') for row in scopes} & {row['id'] for row in data['catalogs']}):
                            raise definitions.DefinitionError('프로젝트에 연결된 L2 업무범위만 설정할 수 있습니다.')
                        selected = selected_group_ids(request.POST)
                        if not set(selected).issubset({row['id'] for row in data['groups']}):
                            raise definitions.DefinitionError('유효한 GIS 적용그룹을 선택하세요.')
                        cur.execute('DELETE FROM gis.project_reference_group WHERE project_id=%s AND catalog_l2_id=%s', [str(project_id), l2])
                        for group in selected:
                            cur.execute('INSERT INTO gis.project_reference_group(project_id,catalog_l2_id,group_id) VALUES (%s,%s,%s)', [str(project_id),l2,group])
                        config['reference_groups'][l2] = selected
                    elif action=='group':
                        group=request.POST.get('group') or None
                        if group and group not in {g['id'] for g in data['groups']}: raise definitions.DefinitionError('그룹을 선택하세요.')
                        config['group_id']=group
                    elif action=='add':
                        fid=definitions.identifier(request.POST.get('item')); layer_id=definitions.identifier(request.POST.get('layer'))
                        f=next((f for f in context['available'] if f['id']==fid),None)
                        if not f or layer_id not in layer_ids or f['source_layer_id'] and f['source_layer_id']!=layer_id:
                            raise definitions.DefinitionError('프로젝트에서 사용할 수 없는 필드 또는 레이어입니다.')
                        config['additions'][fid]=sorted(set(config['additions'].get(fid,[])+[layer_id]))
                    elif action=='remove':
                        fid=definitions.identifier(request.POST.get('item')); layer_id=definitions.identifier(request.POST.get('layer'))
                        if any(l['group_id']==config['group_id'] and l['layer_id']==layer_id and l['field_id']==fid for l in data['group_fields']):
                            raise definitions.DefinitionError('그룹에서 상속한 필드는 제거할 수 없습니다.')
                        config['private_items'].pop(fid,None)
                        remaining=[v for v in config['additions'].get(fid,[]) if v!=layer_id]
                        if remaining: config['additions'][fid]=remaining
                        else: config['additions'].pop(fid,None)
                    elif action=='create':
                        layer_id=definitions.identifier(request.POST.get('layer'))
                        if layer_id not in layer_ids: raise definitions.DefinitionError('허용되지 않은 레이어입니다.')
                        label,kind,length,precision,scale,order=field_values(request.POST)
                        fid=str(uuid4())
                        config['private_items'][fid]={'id':fid,'label':label,'kind':kind,'max_length':length,
                            'precision':precision,'scale':scale,'sort_order':order,'source_layer_id':layer_id,
                            'physical_name':None,'widget_type':kind,'visible':True,'required':False,'readonly':False}
                    else: raise definitions.DefinitionError('지원하지 않는 요청입니다.')
                    cur.execute('''INSERT INTO gis.project_definition(project_id,group_id,additions,private_items,overrides)
                        VALUES (%s,%s,%s::jsonb,%s::jsonb,%s::jsonb) ON CONFLICT(project_id) DO UPDATE SET
                        group_id=EXCLUDED.group_id,additions=EXCLUDED.additions,private_items=EXCLUDED.private_items,
                        overrides=EXCLUDED.overrides''', [str(project_id),config['group_id'],
                        json.dumps(config['additions']),json.dumps(config['private_items']),json.dumps(config['overrides'])])
                context['definition']=central.resolve(data,config,plan['layers'],include_unavailable=True)
                photo_data = central_photo_snapshot()
                context['photo_policies'] = []
                if photo_data:
                    photo_scopes = _paired_scopes(alias, project.id)
                    for layer in plan['layers']:
                        policy = gis_photo_policy.resolve(photo_data, photo_scopes, layer['id'])
                        if policy:
                            context['photo_policies'].append({'layer': layer, 'policy': policy})
                context['selected_group']=config['group_id']
                context['reference_groups_ready'] = data.get('reference_groups_ready') and config.get('reference_groups_ready')
                context['reference_scopes'] = [
                    {**row, 'groups': [{**group, 'selected': group['id'] in config.get('reference_groups', {}).get(row['id'], [])}
                                       for group in data['groups']]}
                    for row in data['catalogs'] if row['id'] in {scope.get('2') for scope in scopes}]

            if request.method=='POST': return redirect('gis:project_form_configuration',project_id=project_id)
    except (definitions.DefinitionError, gis_photo_policy.PhotoPolicyError) as exc: context['error']=str(exc)
    except DatabaseError:
        logger.warning('GIS project form configuration unavailable')
        context['error']='폼 구성을 읽거나 저장하지 못했습니다.'
    return render(request,'geoflow_ops/gis/form_configuration.html',context,status=400 if context.get('error') else 200)
