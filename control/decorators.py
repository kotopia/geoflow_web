# control/decorators.py
from functools import wraps
from django.http import HttpResponseForbidden
from django.db import connections
from control.middleware import current_db_alias
from control.services_identity import ensure_user_from_request, to_group_uuid
from control.services_acl import user_has_perm
import logging
logger = logging.getLogger(__name__)

def require_central_admin(view_func):
    @wraps(view_func)
    def _wrap(request, *args, **kwargs):
        uid = ensure_user_from_request(request)
        if not uid:
            return HttpResponseForbidden("권한이 없습니다.")
        with connections["default"].cursor() as cur:
            cur.execute("SELECT is_staff FROM users WHERE id=%s", [uid])
            row = cur.fetchone()
        if not row or not row[0]:
            return HttpResponseForbidden("권한이 없습니다.")
        return view_func(request, *args, **kwargs)
    return _wrap

def _is_staff(email: str) -> bool:
    if not email:
        return False
    with connections["default"].cursor() as cur:
        cur.execute("SELECT COALESCE(is_staff, FALSE) FROM users WHERE email=%s LIMIT 1", [email])
        row = cur.fetchone()
    return bool(row and row[0])

def require_staff(view):
    def _wrap(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return HttpResponseForbidden("로그인이 필요합니다.")
        if _is_staff(request.user.username):
            return view(request, *args, **kwargs)
        return HttpResponseForbidden("중앙 관리자만 접근 가능합니다.")
    return _wrap

def require_perm(perm_code):
    def deco(view):
        def _wrap(request, *args, **kwargs):
            # 1) 중앙 관리자는 무조건 통과
            if request.user.is_authenticated and _is_staff(request.user.username):
                return view(request, *args, **kwargs)

            # 2) 이하 테넌트 권한 검사(기존 로직)
            group_id = request.session.get("group_id")
            if not group_id:
                return HttpResponseForbidden("권한이 없습니다. (세션/계정 매핑 실패)")
            # ... 기존 perm 체크 계속 ...
            return view(request, *args, **kwargs)  # 실제 체크 코드 뒤에 위치
        return _wrap
    return deco