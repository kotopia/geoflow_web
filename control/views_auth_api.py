# control/views_auth_api.py (새 파일, 또는 webgisapp에 넣어도 됨)
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.contrib.auth import get_user_model, login
from django.db import connections
import bcrypt

@csrf_exempt
def api_login(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)

    email = request.POST.get("email")
    password = request.POST.get("password")
    if not email or not password:
        return JsonResponse({"error": "missing email/password"}, status=400)

    with connections["default"].cursor() as cur:
        # users에서 해시 조회
        cur.execute("SELECT id::text, password_hash FROM users WHERE email=%s LIMIT 1", [email])
        row = cur.fetchone()
        if not row:
            return JsonResponse({"error": "user not found"}, status=401)
        user_uuid, pw_hash = row

        if not bcrypt.checkpw(password.encode(), pw_hash.encode()):
            return JsonResponse({"error": "bad credentials"}, status=401)

        # 멤버십(아무거나 첫 그룹) + alias
        cur.execute("""
            SELECT ugm.group_id::text, gcfg.db_alias
            FROM user_group_map ugm
            JOIN group_db_config gcfg ON gcfg.group_id = ugm.group_id
            WHERE ugm.user_id = %s AND ugm.status='active'
            ORDER BY ugm.created_at ASC
            LIMIT 1
        """, [user_uuid])
        r2 = cur.fetchone()
        if not r2:
            return JsonResponse({"error": "no active membership"}, status=403)

        group_uuid, db_alias = r2

    # 장고 사용자(브라우저 세션용) 동기화
    # username=email 로 로컬 auth_user 보장
    User = get_user_model()
    user_obj, _ = User.objects.get_or_create(username=email, defaults={"email": email, "is_active": True})
    user_obj.backend = "django.contrib.auth.backends.ModelBackend"
    login(request, user_obj)

    request.session["group_uuid"]      = group_uuid
    request.session["tenant_db_alias"] = db_alias
    request.session["group_id"] = group_uuid    # 호환
    request.session["db_key"]   = db_alias      # 호환

    return JsonResponse({"ok": True, "group_id": group_uuid, "db_alias": db_alias})
