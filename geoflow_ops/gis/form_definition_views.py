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
from control.services.gis_definitions import field_values
from .views import _require_gis_view, _require_project_gis_access
from .qgis_views import _require_qgis_context, _require_project
from geoflow_ops.services.project_access import project_access_policy

logger=logging.getLogger(__name__)


@login_required
@require_GET
def definition_api(request, project_id):
    alias=_require_qgis_context(request)
    _project,_policy,plan=_require_project(request,alias,project_id)
    data=central.central_snapshot()
    if data is None: return JsonResponse({'ok':False,'error':'form_definition_schema_pending'},status=503)
    try:
        with connections[alias].cursor() as cur:
            config=central.project_config(cur,project_id)
        payload=central.resolve(data,config,plan['layers'])
    except definitions.DefinitionError as exc: return JsonResponse({'ok':False,'error':str(exc)},status=409)
    response=JsonResponse({'ok':True,**payload})
    response['Cache-Control']='private, no-store'
    return response


@login_required
@require_http_methods(['GET','POST'])
def project_configuration(request,project_id):
    alias=_require_gis_view(request)
    project,plan=_require_project_gis_access(request,alias,project_id)
    can_edit=project_access_policy(request,alias).can_edit_project(project.id)
    if request.method=='POST' and not can_edit: raise PermissionDenied('프로젝트 설정 권한이 없습니다.')
    context={'project':project,'plan':plan,'can_edit':can_edit,'features':plan['layers']}
    try:
        data=central.central_snapshot()
        context['ready']=data is not None
        if data is None: raise definitions.DefinitionError('중앙 업무정의 구조 적용 전입니다.')
        names={l['standard_name'] for l in data['layers']}
        context['features']=data['layers']
        context['groups']=data['groups']
        context['available']=[f for f in data['fields'] if not f['source_layer'] or f['source_layer'] in names]
        with transaction.atomic(using=alias),connections[alias].cursor() as cur:
            cur.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',['gis.definition.project:'+str(project_id)])
            config=central.project_config(cur,project_id)
            if request.method=='POST':
                cur.execute("SELECT to_regclass('gis.project_definition')")
                if not cur.fetchone()[0]: raise definitions.DefinitionError('프로젝트 구성 저장 구조 적용 전입니다.')
                action=request.POST.get('action')
                if action=='group':
                    group=request.POST.get('group') or None
                    if group and group not in {g['id'] for g in data['groups']}: raise definitions.DefinitionError('그룹을 선택하세요.')
                    config['group_id']=group
                elif action=='add':
                    fid=definitions.identifier(request.POST.get('item')); name=request.POST.get('layer')
                    f=next((f for f in context['available'] if f['id']==fid),None)
                    if not f or name not in names or f['source_layer'] and f['source_layer']!=name:
                        raise definitions.DefinitionError('프로젝트에서 사용할 수 없는 필드 또는 레이어입니다.')
                    config['additions'][fid]=sorted(set(config['additions'].get(fid,[])+[name]))
                elif action=='remove':
                    fid=definitions.identifier(request.POST.get('item')); name=request.POST.get('layer')
                    if any(l['group_id']==config['group_id'] and l['layer_name']==name and l['field_id']==fid for l in data['group_fields']):
                        raise definitions.DefinitionError('그룹에서 상속한 필드는 제거할 수 없습니다.')
                    config['private_items'].pop(fid,None)
                    remaining=[v for v in config['additions'].get(fid,[]) if v!=name]
                    if remaining: config['additions'][fid]=remaining
                    else: config['additions'].pop(fid,None)
                elif action=='create':
                    name=request.POST.get('layer')
                    if name not in names: raise definitions.DefinitionError('허용되지 않은 레이어입니다.')
                    label,kind,length,precision,scale,order=field_values(request.POST)
                    fid=str(uuid4())
                    config['private_items'][fid]={'id':fid,'label':label,'kind':kind,'max_length':length,
                        'precision':precision,'scale':scale,'sort_order':order,'source_layer':name,'physical_name':None}
                else: raise definitions.DefinitionError('지원하지 않는 요청입니다.')
                cur.execute('''INSERT INTO gis.project_definition(project_id,group_id,additions,private_items)
                    VALUES (%s,%s,%s::jsonb,%s::jsonb) ON CONFLICT(project_id) DO UPDATE SET
                    group_id=EXCLUDED.group_id,additions=EXCLUDED.additions,private_items=EXCLUDED.private_items''',
                    [str(project_id),config['group_id'],json.dumps(config['additions']),json.dumps(config['private_items'])])
            context['definition']=central.resolve(data,config,plan['layers'],include_unavailable=True)
            context['selected_group']=config['group_id']
        if request.method=='POST': return redirect('gis:project_form_configuration',project_id=project_id)
    except definitions.DefinitionError as exc: context['error']=str(exc)
    except DatabaseError:
        logger.warning('GIS project form configuration unavailable')
        context['error']='폼 구성을 읽거나 저장하지 못했습니다.'
    return render(request,'geoflow_ops/gis/form_configuration.html',context,status=400 if context.get('error') else 200)
