"""Personal central preferences, never a source of business authorization."""
import json
from uuid import UUID, uuid4

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import connections, transaction
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from control.gf_authz.permissions import gf_has_perm
from control.gf_authz.services import _resolve_request_identity, _resolve_group_id
from .services.entity_access import require_tenant_context
from .services.contract_filter_definition import validate_definition


def preference_scope(request):
    tenant = require_tenant_context(request)
    if not gf_has_perm(request, 'contracts.view'):
        raise PermissionDenied
    try:
        group = str(UUID(_resolve_group_id(request)))
    except (ValueError, TypeError, AttributeError):
        raise PermissionDenied
    alias = getattr(settings, 'CENTRAL_DB_ALIAS', 'default')
    # Revalidate identity, active membership AND mapping; never trust client IDs.
    with connections[alias].cursor() as cur:
        cur.execute('''SELECT DISTINCT u.id FROM users u
            JOIN user_group_map m ON m.user_id=u.id
            JOIN groups g ON g.id=m.group_id
            JOIN group_db_config c ON c.group_id=g.id
            WHERE lower(u.email)=lower(%s) AND u.is_active=TRUE
              AND m.group_id=%s AND m.status='active' AND g.status='active'
              AND c.db_alias=%s''', [_resolve_request_identity(request), group, tenant])
        row = cur.fetchone()
    if not row:
        raise PermissionDenied
    return alias, str(row[0]), group


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def contract_saved_filters(request):
    alias, user, group = preference_scope(request)
    # Check availability without swallowing unrelated database failures.
    with connections[alias].cursor() as cur:
        cur.execute("SELECT to_regclass('public.saved_filters')")
        if not cur.fetchone()[0]:
            return JsonResponse({'error': '필터 저장 기능이 아직 준비되지 않았습니다.'}, status=503)
    if request.method == 'GET':
        with connections[alias].cursor() as cur:
            cur.execute('''SELECT id, name, filter_json FROM saved_filters
                WHERE user_id=%s AND group_id=%s AND module=%s ORDER BY name,id''', [user, group, 'contracts'])
            rows = [{'id': str(r[0]), 'name': r[1], 'definition': json.loads(r[2]) if isinstance(r[2], str) else r[2]} for r in cur.fetchall()]
        return JsonResponse({'filters': rows})
    try:
        if len(request.body) > 32000:
            raise ValueError('필터가 너무 큽니다.')
        body = json.loads(request.body)
        name = body.get('name', '').strip()
        if not name or len(name) > 100:
            raise ValueError('이름은 1~100자로 입력하세요.')
        definition = validate_definition(body.get('definition'))
    except (ValueError, TypeError, AttributeError):
        return JsonResponse({'error': '필터 이름과 조건을 확인하세요.'}, status=400)
    with transaction.atomic(using=alias), connections[alias].cursor() as cur:
        # Serialize quota checks per identity; also protects concurrent tabs.
        cur.execute('SELECT id FROM users WHERE id=%s FOR UPDATE', [user])
        cur.execute('''SELECT count(*) FROM saved_filters WHERE user_id=%s AND group_id=%s AND module=%s AND name<>%s''', [user, group, 'contracts', name])
        if cur.fetchone()[0] >= 100:
            return JsonResponse({'error': '개인 필터는 최대 100개까지 저장할 수 있습니다.'}, status=400)
        cur.execute('''INSERT INTO saved_filters(id,user_id,group_id,module,name,filter_json)
            VALUES(%s,%s,%s,%s,%s,%s::jsonb)
            ON CONFLICT(user_id,group_id,module,name) DO UPDATE
              SET filter_json=EXCLUDED.filter_json,updated_at=now()
            RETURNING id''', [str(uuid4()), user, group, 'contracts', name, json.dumps(definition)])
        pk = str(cur.fetchone()[0])
    response = JsonResponse({'id': pk, 'name': name, 'definition': definition})
    response['Cache-Control'] = 'no-store'
    return response
