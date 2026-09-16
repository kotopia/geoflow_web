import logging
from django.db import connections, transaction, IntegrityError, DatabaseError
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods
from control.decorators import require_central_admin
from control.services import gis_definitions as definitions
from control.services.gis_admin import guard_definition_deletion

logger=logging.getLogger(__name__)


@require_central_admin
@require_http_methods(['GET','POST'])
def dashboard(request):
    error=None
    try:
        with transaction.atomic(using='default'):
            with connections['default'].cursor() as cur:
                if not definitions.ready(cur):
                    if request.method=='POST':
                        return JsonResponse({'ok':False,'error':'중앙 업무정의 구조 적용 전입니다.'},status=503)
                    return render(request,'control/gis/definitions.html',{'ready':False})
                if request.method=='POST':
                    cur.execute("SELECT pg_advisory_xact_lock(hashtext('geoflow.central.gis.definitions'))")
                    guard_definition_deletion(cur,request.POST)
                    uid=definitions.mutate(cur,request.POST)
                payload=definitions.snapshot(cur)
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
