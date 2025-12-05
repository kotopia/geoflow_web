from django.db import connections
from control.services_identity import ensure_user_from_request

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