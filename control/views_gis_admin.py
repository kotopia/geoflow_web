import logging
from django.db import connections, transaction, IntegrityError, DatabaseError
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods, require_POST
from control.decorators import require_central_admin
from control.models import GroupDBConfig
from control.services import gis_definitions as definitions
from control.services.gis_admin import guard_definition_deletion
from control.services import gis_schema_manager
from control.services import gis_schema_execution

logger=logging.getLogger(__name__)


def _definition_payload(cur):
    payload=definitions.snapshot(cur)
    payload['admin_schema_ready']=gis_schema_manager.admin_schema_ready(cur)
    if payload['admin_schema_ready']:
        payload['schema_changes']=gis_schema_manager.schema_change_snapshot(cur)
        payload['schema_change_tenants']=gis_schema_manager.schema_change_tenant_snapshot(cur)
        payload['change_log']=gis_schema_manager.change_log_snapshot(cur)
    payload['tenants']=list(
        GroupDBConfig.objects.using('default').select_related('group')
        .filter(group__status='active').exclude(db_alias='default')
        .order_by('group__name')
        .values('group_id','group__code','group__name')
    )
    return payload


def _physical_field_update(request):
    actor=gis_schema_manager.actor_name(request)
    field_id=request.POST.get('id')
    rename=None
    alter_type=None
    try:
        with transaction.atomic(using='default'):
            with connections['default'].cursor() as cur:
                if not definitions.ready(cur):
                    return JsonResponse({'ok':False,'error':'중앙 업무정의 구조 적용 전입니다.'},status=503)
                cur.execute("SELECT pg_advisory_xact_lock(hashtext('geoflow.central.gis.definitions'))")
                before=gis_schema_manager.field_state(cur,field_id)
                if not before:
                    raise definitions.DefinitionError('물리 필드를 찾을 수 없습니다.')
                requested_name=gis_schema_manager.identifier(
                    request.POST.get('physical_name') or before['physical_name'],
                    'DB 필드명',
                )
                requested_type=gis_schema_manager.storage_type(
                    data_kind=request.POST.get('data_type_kind'),
                    db_type=request.POST.get('storage_data_type') or before.get('storage_data_type'),
                    max_length=request.POST.get('max_length') if request.POST.get('max_length') not in (None,'') else before.get('max_length'),
                    precision=request.POST.get('precision') if request.POST.get('precision') not in (None,'') else before.get('precision'),
                    scale=request.POST.get('scale') if request.POST.get('scale') not in (None,'') else before.get('scale'),
                )
                current_type=gis_schema_manager.storage_type(
                    db_type=before.get('storage_data_type') or before.get('storage_udt_name') or 'text',
                    max_length=before.get('max_length'),
                    precision=before.get('precision'),
                    scale=before.get('scale'),
                )
                uid=gis_schema_manager.mutate_admin(cur,request.POST,actor=actor)
                if requested_name != before['physical_name']:
                    pending=gis_schema_manager.find_incomplete_rename(cur,uid)
                    if not pending:
                        raise definitions.DefinitionError('물리 필드명 변경 요청을 찾을 수 없습니다.')
                    rename={
                        'change_id':pending['id'],
                        'old_name':before['physical_name'],
                        'new_name':requested_name,
                    }
                elif requested_type != current_type:
                    pending=gis_schema_manager.find_incomplete_alter_type(cur,uid)
                    if not pending:
                        raise definitions.DefinitionError('DB 타입 변경 요청을 찾을 수 없습니다.')
                    alter_type={
                        'change_id':pending['id'],
                        'old_type':current_type,
                        'new_type':requested_type,
                    }

        if rename:
            try:
                result=gis_schema_execution.apply_rename_from_field_save(
                    rename['change_id'],actor=actor
                )
            except definitions.DefinitionError as exc:
                with connections['default'].cursor() as cur:
                    payload=_definition_payload(cur)
                return JsonResponse({
                    'ok':False,
                    'error':'물리 필드명 변경에 실패했습니다. 기존 필드명은 유지됩니다. '+str(exc),
                    'id':uid,
                    'data':payload,
                },status=409)
            with connections['default'].cursor() as cur:
                payload=_definition_payload(cur)
            if result['status'] != 'APPLIED':
                details='; '.join(
                    f"{item['tenant_name']}: {item['error']}" for item in result.get('failures',[])
                )
                error='물리 필드명 변경에 실패했습니다. 기존 필드명은 유지됩니다.'
                if details:
                    error += ' ' + details
                return JsonResponse(
                    {'ok':False,'error':error,'id':uid,'data':payload,
                     'rename':result},
                    status=409,
                )
            return JsonResponse({
                'ok':True,'id':uid,'data':payload,
                'message':f"물리 필드명을 {rename['old_name']} → {rename['new_name']}로 변경했습니다.",
                'rename':result,
            })

        if alter_type:
            try:
                result=gis_schema_execution.apply_type_from_field_save(
                    alter_type['change_id'],actor=actor
                )
            except definitions.DefinitionError as exc:
                with connections['default'].cursor() as cur:
                    payload=_definition_payload(cur)
                return JsonResponse({
                    'ok':False,
                    'error':'DB 타입 변경에 실패했습니다. 기존 정의와 컬럼 타입은 유지됩니다. '+str(exc),
                    'id':uid,
                    'data':payload,
                },status=409)
            with connections['default'].cursor() as cur:
                payload=_definition_payload(cur)
            if result['status'] != 'APPLIED':
                details='; '.join(
                    f"{item['tenant_name']}: {item['error']}" for item in result.get('failures',[])
                )
                error='DB 타입 변경에 실패했습니다. 기존 정의와 컬럼 타입은 유지됩니다.'
                if details:
                    error += ' ' + details
                return JsonResponse(
                    {'ok':False,'error':error,'id':uid,'data':payload,'alter_type':result},
                    status=409,
                )
            return JsonResponse({
                'ok':True,'id':uid,'data':payload,
                'message':f"DB 타입을 {alter_type['old_type']} → {alter_type['new_type']}으로 변경했습니다.",
                'alter_type':result,
            })

        with connections['default'].cursor() as cur:
            payload=_definition_payload(cur)
        return JsonResponse({'ok':True,'id':uid,'data':payload,'message':'저장했습니다.'})
    except definitions.DefinitionError as exc:
        return JsonResponse({'ok':False,'error':str(exc)},status=409)
    except DatabaseError:
        logger.exception('GIS physical field update database failure')
        return JsonResponse({'ok':False,'error':'GIS 물리 필드 수정 중 DB 오류가 발생했습니다.'},status=503)
    except Exception:
        logger.exception('GIS physical field update failure')
        return JsonResponse({'ok':False,'error':'GIS 물리 필드 변경을 완료하지 못했습니다. 기존 정의와 컬럼 상태는 유지됩니다.'},status=500)


@require_central_admin
@require_http_methods(['GET','POST'])
def dashboard(request):
    error=None
    if request.method=='POST' and request.POST.get('action')=='physical_field_update_admin':
        return _physical_field_update(request)
    try:
        with transaction.atomic(using='default'):
            with connections['default'].cursor() as cur:
                if not definitions.ready(cur):
                    if request.method=='POST':
                        return JsonResponse({'ok':False,'error':'중앙 업무정의 구조 적용 전입니다.'},status=503)
                    return render(request,'control/gis/definitions.html',{'ready':False})
                if request.method=='POST':
                    cur.execute("SELECT pg_advisory_xact_lock(hashtext('geoflow.central.gis.definitions'))")
                    action=request.POST.get('action','')
                    if action.endswith('_admin'):
                        uid=gis_schema_manager.mutate_admin(
                            cur,request.POST,actor=gis_schema_manager.actor_name(request)
                        )
                    else:
                        guard_definition_deletion(cur,request.POST)
                        legacy_target=None
                        legacy_before=None
                        requested_id=request.POST.get('id')
                        audit_ready=gis_schema_manager.admin_schema_ready(cur)
                        if audit_ready and action in ('group','delete_group'):
                            legacy_target='GROUP'
                            legacy_before=gis_schema_manager.business_group_state(cur,requested_id) if requested_id else None
                        elif audit_ready and action=='layer':
                            legacy_target='LAYER'
                            legacy_before=gis_schema_manager.layer_state(cur,requested_id) if requested_id else None
                        elif audit_ready and action in ('field','standard_field','delete_field'):
                            legacy_target='FIELD'
                            legacy_before=gis_schema_manager.field_state(cur,requested_id) if requested_id else None
                        uid=definitions.mutate(cur,request.POST)
                        if legacy_target and audit_ready:
                            after=(gis_schema_manager.business_group_state(cur,uid) if legacy_target=='GROUP'
                                   else gis_schema_manager.layer_state(cur,uid) if legacy_target=='LAYER'
                                   else gis_schema_manager.field_state(cur,uid))
                            gis_schema_manager.audit(
                                cur,actor=gis_schema_manager.actor_name(request),
                                target_type=legacy_target,target_id=uid,
                                change_type='LEGACY_'+action.upper(),
                                before=legacy_before,after=after,
                            )
                payload=_definition_payload(cur)
        if request.method=='POST': return JsonResponse({'ok':True,'id':uid,'data':payload})
        return render(request,'control/gis/definitions.html',{'ready':True,'definition_data':payload})
    except definitions.DefinitionError as exc:
        error=str(exc)
    except IntegrityError:
        error='중복된 값이거나 다른 항목에서 사용 중입니다. 연결·조건 규칙을 먼저 확인하세요.'
    except DatabaseError:
        logger.warning('Central GIS definitions unavailable')
        error='중앙 업무정의를 읽거나 저장하지 못했습니다.'
    if request.method=='POST': return JsonResponse({'ok':False,'error':error},status=400)
    return render(request,'control/gis/definitions.html',{'error':error,'ready':False},status=503)


@require_central_admin
@require_POST
def schema_change_command(request, change_id, command):
    """Central-admin-only command boundary for GIS schema changes."""
    try:
        actor=gis_schema_manager.actor_name(request)
        if command=='inspect':
            change=gis_schema_execution.get_change(str(change_id))
            return JsonResponse({'ok':True,'impact':gis_schema_execution.inspect_all(change)})
        if command=='approve':
            impact=gis_schema_execution.approve(
                str(change_id),actor=actor,
                allow_data_loss=request.POST.get('allow_data_loss') in ('1','true','on'),
            )
            return JsonResponse({'ok':True,'impact':impact})
        if command=='apply':
            tenant_ids=request.POST.getlist('tenant_group_id')
            result=gis_schema_execution.apply(
                str(change_id),tenant_ids,actor=actor,
                confirmation=request.POST.get('confirmation',''),
            )
            ok=result['status'] in ('APPLIED','PARTIAL_APPLIED')
            return JsonResponse({'ok':ok,**result},status=200 if ok else 409)
        return JsonResponse({'ok':False,'error':'지원하지 않는 Schema 명령입니다.'},status=400)
    except definitions.DefinitionError as exc:
        return JsonResponse({'ok':False,'error':str(exc)},status=409)
    except DatabaseError:
        logger.exception('GIS schema change database failure')
        return JsonResponse({'ok':False,'error':'GIS Schema 변경 처리 중 DB 오류가 발생했습니다.'},status=503)
    except Exception:
        logger.exception('GIS schema change execution failure')
        return JsonResponse({'ok':False,'error':'GIS Schema 변경을 완료하지 못했습니다.'},status=500)
