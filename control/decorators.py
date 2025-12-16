# control/decorators.py
from functools import wraps
from django.http import HttpResponseForbidden
from django.db import connections
from control.services_identity import ensure_user_from_request
from control.templatetags.acl_tags import has_perm as _has_perm_tag
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
    @wraps(view)
    def _wrap(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return HttpResponseForbidden("로그인이 필요합니다.")
        if _is_staff(request.user.username):
            return view(request, *args, **kwargs)
        return HttpResponseForbidden("중앙 관리자만 접근 가능합니다.")
    return _wrap

def require_perm(perm_code: str):
    """
    세션 기반 권한 검사 데코레이터.
    - 중앙 관리자(is_staff)는 무조건 통과
    - 그 외에는 템플릿 태그 has_perm과 동일한 규칙으로 검사
    """
    def deco(view):
        @wraps(view)
        def _wrap(request, *args, **kwargs):
            # 1) 중앙 관리자는 우선 통과
            if request.user.is_authenticated and _is_staff(request.user.username):
                return view(request, *args, **kwargs)

            # 2) 동일 로직 재사용(acl_tags.has_perm)
            ctx = {"request": request}
            if not _has_perm_tag(ctx, perm_code):
                logger.info("FORBIDDEN: user=%s perm=%s group=%s perms=%s",
                            getattr(request.user, "email", None),
                            perm_code,
                            request.session.get("group_id") or request.session.get("group_uuid"),
                            request.session.get("perms"))
                return HttpResponseForbidden("권한이 없습니다: " + perm_code)
            return view(request, *args, **kwargs)
        return _wrap
    return deco
