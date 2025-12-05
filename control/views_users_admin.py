# control/views_users_admin.py
from django.db import connections, transaction
from django.shortcuts import render, redirect
from django.contrib import messages
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.contrib.auth.hashers import make_password
from .decorators import require_staff

import logging
logger = logging.getLogger(__name__)

@csrf_protect
def set_password_view(request, token):
    # 1) 토큰 검증
    with connections["default"].cursor() as cur:
        cur.execute("""
          SELECT prt.user_id::text, u.email, prt.expires_at, prt.used
            FROM password_reset_tokens prt
            JOIN users u ON u.id = prt.user_id
           WHERE prt.token=%s
        """, [str(token)])
        row = cur.fetchone()
    if not row:
        return render(request, "control/set_password.html", {"invalid": True})

    user_id, email, expires_at, used = row
    if used or expires_at < timezone.now():
        return render(request, "control/set_password.html", {"expired": True, "email": email})

    if request.method == "GET":
        return render(request, "control/set_password.html", {"email": email})

    # POST
    pw1 = (request.POST.get("password") or "").strip()
    pw2 = (request.POST.get("password2") or "").strip()
    if len(pw1) < 8 or pw1 != pw2:
        messages.error(request, "비밀번호가 조건에 맞지 않거나 일치하지 않습니다.")
        return render(request, "control/set_password.html", {"email": email})

    hashed = make_password(pw1)
    with transaction.atomic():
        with connections["default"].cursor() as cur:
            # 2) 비번 저장 + 이메일 인증 처리
            cur.execute("""
              UPDATE users SET password_hash=%s, email_verified=TRUE, updated_at=now()
               WHERE id=%s
            """, [hashed, user_id])
            # 3) 토큰 소모
            cur.execute("""
              UPDATE password_reset_tokens SET used=TRUE WHERE token=%s
            """, [str(token)])

    messages.success(request, "비밀번호가 설정되었습니다. 이제 로그인할 수 있습니다.")
    return redirect("login")

@require_staff
def users_list_admin(request):
    with connections["default"].cursor() as cur:
        cur.execute("""
          SELECT u.id::text, u.email, u.is_active, u.email_verified, u.last_login,
                 (SELECT COUNT(*) FROM user_group_map ugm WHERE ugm.user_id=u.id) AS groups_count
            FROM users u
           ORDER BY u.created_at DESC
           LIMIT 500
        """)
        rows = cur.fetchall()
    users = [{
        "id": r[0], "email": r[1], "is_active": r[2],
        "email_verified": r[3], "last_login": r[4], "groups_count": r[5],
    } for r in rows]
    return render(request, "control/users_list_admin.html", {"users": users})

@require_staff
def users_detail_admin(request, user_id):
    with connections["default"].cursor() as cur:
        cur.execute("""
          SELECT u.id::text, u.email, u.is_active, u.email_verified, u.last_login, u.created_at, u.updated_at
            FROM users u
           WHERE u.id=%s
        """, [str(user_id)])
        u = cur.fetchone()
        if not u:
            messages.error(request, "사용자를 찾을 수 없습니다.")
            return redirect("users_list_admin")
        cur.execute("""
          SELECT g.id::text, g.name, r.code, r.name
            FROM user_group_map ugm
            JOIN groups g ON g.id=ugm.group_id
            JOIN roles  r ON r.id=ugm.role_id
           WHERE ugm.user_id=%s
        """, [str(user_id)])
        memberships = cur.fetchall()

        # 대기 중인 권한요청(이메일 기준)
        email = u[1]
        cur.execute("""
          SELECT jr.id::text, g.name, r.code, jr.status, jr.created_at
            FROM join_requests jr
            JOIN groups g ON g.id=jr.group_id
            JOIN roles  r ON r.id=jr.role_id
           WHERE COALESCE(jr.user_id::text,'')=%s OR lower(jr.email)=lower(%s)
           ORDER BY jr.created_at DESC
        """, [str(user_id), email])

        requests = cur.fetchall()

    ctx = {
        "user": {"id": u[0], "email": u[1], "is_active": u[2],
                 "email_verified": u[3], "last_login": u[4],
                 "created_at": u[5], "updated_at": u[6]},
        "memberships": [{"group_id": m[0], "group_name": m[1], "role_code": m[2], "role_name": m[3]} for m in memberships],
        "requests": [{"id": r[0], "group_name": r[1], "role_code": r[2], "status": r[3], "created_at": r[4]} for r in requests],
    }
    return render(request, "control/users_detail_admin.html", ctx)

@require_staff
@csrf_protect
def users_delete_admin(request, user_id):
    if request.method != "POST":
        messages.error(request, "잘못된 접근입니다.")
        return redirect("users_detail_admin", user_id=user_id)

    with transaction.atomic():
        with connections["default"].cursor() as cur:
            # 이메일 확보(연쇄 삭제용)
            cur.execute("SELECT email FROM users WHERE id=%s", [str(user_id)])
            row = cur.fetchone()
            if not row:
                messages.error(request, "사용자를 찾을 수 없습니다.")
                return redirect("users_list_admin")
            email = row[0]

            # 1) 멤버십 제거 (FK CASCADE가 없을 경우 수동 삭제)
            cur.execute("DELETE FROM user_group_map WHERE user_id=%s", [str(user_id)])

            # 2) 대기 요청 제거 (user_id 또는 email 로 기록된 케이스 모두)
            cur.execute("DELETE FROM join_requests WHERE COALESCE(user_id::text,'')=%s OR lower(email)=lower(%s)",
                        [str(user_id), email])

            # 3) 비번 토큰 제거
            cur.execute("DELETE FROM password_reset_tokens WHERE user_id=%s", [str(user_id)])

            # 4) (선택) 기타 사용자 연관 테이블 정리 필요 시 이곳에 추가

            # 5) 최종 users 삭제
            cur.execute("DELETE FROM users WHERE id=%s", [str(user_id)])

    messages.success(request, f"{email} 사용자 및 연관 데이터가 삭제되었습니다.")
    return redirect("users_list_admin")

@require_staff
def users_assign_group_admin(request, user_id):
    if request.method != "POST":
        return redirect("users_detail_admin", user_id=user_id)
    group_id = request.POST.get("group_id")
    role_id  = request.POST.get("role_id")
    if not group_id or not role_id:
        messages.error(request, "그룹과 역할을 선택하세요.")
        return redirect("users_detail_admin", user_id=user_id)

    with connections["default"].cursor() as cur:
        cur.execute("""
          INSERT INTO user_group_map(id, user_id, group_id, role_id, status, created_at, updated_at)
          VALUES (gen_random_uuid(), %s, %s, %s, 'active', now(), now())
          ON CONFLICT (user_id, group_id)
          DO UPDATE SET role_id=EXCLUDED.role_id, status='active', updated_at=now()
        """, [user_id, group_id, role_id])
    messages.success(request, "그룹/역할이 지정되었습니다.")
    return redirect("users_detail_admin", user_id=user_id)

def dashboard(request):
    logger.info("CENTRAL_VIEW dashboard: scope=%s alias=%s",
                request.session.get('scope'), request.session.get('tenant_db_alias'))
    return render(request, 'control/dashboard.html', {})
