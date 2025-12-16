from django.db import connections
from control.services_identity import ensure_user_from_request
from control.services import central_repo as C

def central_flags(request):
    is_staff = False
    if getattr(request, "user", None) and request.user.is_authenticated:
        with connections["default"].cursor() as cur:
            cur.execute("SELECT is_staff FROM users WHERE email=%s LIMIT 1", [request.user.username])
            row = cur.fetchone()
            is_staff = bool(row and row[0])
    return {
        "central_is_staff": is_staff,
        "current_group_id": request.session.get("group_id"),
    }

def perms_context(request):
    """
    현재 그룹에서의 역할 전체만 템플릿에 주입.
    세션에 없으면 중앙에서 지연 로딩.
    """
    roles = request.session.get("roles")
    if roles is None:
        roles = []
        user_uuid = ensure_user_from_request(request)
        group_id  = request.session.get("group_uuid") or request.session.get("group_id")
        if user_uuid and group_id:
            try:
                roles = C.list_roles_for_user_in_group(user_uuid, group_id)
            except Exception:
                roles = []
        request.session["roles"] = roles

    return {"current_roles": roles}