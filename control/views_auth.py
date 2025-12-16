from django.conf import settings
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.contrib.auth import get_user_model, login, logout
from django.shortcuts import render, redirect
from django.http import HttpResponseForbidden
from django.db import connections
from django.contrib.auth.hashers import check_password, make_password, identify_hasher
from django.urls import reverse
from control.services import central_repo as C
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.middleware.csrf import rotate_token

from control.services_identity import to_group_uuid, ensure_user_from_request
from control.models import UserGroupMap

import logging
logger = logging.getLogger(__name__)

@require_http_methods(["GET", "POST"])
@csrf_protect
@ensure_csrf_cookie
def login_view(request):

    if request.user.is_authenticated:
        return redirect("after_login")
    
    # ✅ 세션/로그아웃 정리는 GET일 때만 수행 (불필요한 세션 리셋 최소화)
    if request.method == "GET":
        logout(request)
        request.session.flush()

    if request.method == "POST":
        email = (request.POST.get("email") or request.POST.get("username") or "").strip().lower()
        pw    = (request.POST.get("password") or "")

        if not email or not pw:
            return render(request, "control/login.html", {"error": "이메일/비밀번호를 입력하세요."})

        central_alias = getattr(settings, "CENTRAL_DB_ALIAS", "default")

        # 1) 중앙 users에서 사용자/해시 조회
        with connections[central_alias].cursor() as cur:
            cur.execute("""
                SELECT id::text, password_hash
                  FROM users
                 WHERE lower(email) = lower(%s)
                 LIMIT 1
            """, [email])
            row = cur.fetchone()

        if not row:
            return render(request, "control/login.html", {"error": "사용자를 찾을 수 없습니다."})

        user_uuid, pw_hash = row
        if not pw_hash or not str(pw_hash).strip():
            return render(request, "control/login.html", {"error": "비밀번호가 올바르지 않습니다."})

        # 2) 비밀번호 검증(+구형 bcrypt → pbkdf2로 마이그레이션)
        migrate_needed = False
        try:
            if str(pw_hash).startswith(("$2a$", "$2b$", "$2y$")):
                try:
                    import bcrypt
                except Exception:
                    return render(request, "control/login.html", {"error": "서버 설정 오류(bcrypt 미설치). 관리자에게 문의하세요."})
                if not bcrypt.checkpw(pw.encode(), pw_hash.encode()):
                    return render(request, "control/login.html", {"error": "비밀번호가 올바르지 않습니다."})
                migrate_needed = True
            else:
                if not check_password(pw, pw_hash):
                    return render(request, "control/login.html", {"error": "비밀번호가 올바르지 않습니다."})
                try:
                    algo = identify_hasher(pw_hash).algorithm  # 예: 'pbkdf2_sha256'
                    if algo != "pbkdf2_sha256":
                        migrate_needed = True
                except Exception:
                    pass
        except Exception:
            return render(request, "control/login.html", {"error": "비밀번호 검증 중 오류가 발생했습니다."})

        if migrate_needed:
            new_hash = make_password(pw)
            with connections[central_alias].cursor() as cur:
                cur.execute(
                    "UPDATE users SET password_hash=%s, updated_at=now() WHERE id=%s",
                    [new_hash, user_uuid],
                )

        # 3) Django 세션 로그인(auth_user는 통과용 계정)
        User = get_user_model()
        u, _ = User.objects.get_or_create(username=email, defaults={"email": email, "is_active": True})
        u.backend = "django.contrib.auth.backends.ModelBackend"
        login(request, u)
        rotate_token(request)
        # return redirect("after_login")

        # 4) 테넌트 자동 선택: 중앙 레포에서 사용자 소속 테넌트 조회
        # tenants = C.list_tenants_for_user(user_uuid)  # [{'id','code','name','db_alias',...}, ...]
        central_alias = getattr(settings, "CENTRAL_DB_ALIAS", "default")

        try:
            tenants = C.list_tenants_for_user(user_uuid)  # [{'id','code','name','db_alias',...}, ...]
        except Exception as ex:
            logger.exception("AUTH tenants lookup failed: %s", ex)
            tenants = []

        if tenants:
            if len(tenants) == 1:
                t = tenants[0]
                request.session["group_uuid"]      = t["id"]
                request.session["group_id"]        = t["id"]        # 하위호환
                request.session["tenant_db_alias"] = t["db_alias"]
                request.session["db_key"]          = t["db_alias"]  # 하위호환

                # 여러 역할 조회 → 대표 등급 선정 → 세션에 저장
                try:
                    roles = C.list_roles_for_user_in_group(user_uuid, t["id"])
                except Exception:
                    roles = []

                request.session["roles"] = roles     # [{id,name,code}, ...]만 저장

                return redirect("after_login")
            else:
                # 여러 테넌트면 선택 화면으로
                request.session["tenant_candidates"] = tenants
                logger.info(
                    "AUTH: user=%s -> MULTI TENANT candidates=%s",
                    request.user.email, [x["db_alias"] for x in tenants]
                )
                return redirect("group_search")
        else:
            # 소속 없음 → 중앙
            request.session["tenant_db_alias"] = central_alias
            logger.info("AUTH: user=%s -> CENTRAL (no tenant membership)", request.user.email)
            return redirect("after_login")

    # GET
    return render(request, "control/login.html")


CENTRAL = getattr(settings, "CENTRAL_DB_ALIAS", "default")


def post_login_redirect(request):
    alias = request.session.get("tenant_db_alias")
    central_alias = getattr(settings, "CENTRAL_DB_ALIAS", "default")
    gid = request.session.get("group_id")

    logger.info("POST-LOGIN: alias=%s group_id=%s", alias, gid)

    if alias == central_alias or not gid:
        logger.info("POST-LOGIN: route CENTRAL")
        return redirect('control:dashboard')  # 중앙 기본 홈
    logger.info("POST-LOGIN: route TENANT alias=%s", alias)
    return redirect("/")  # 테넌트 기본 홈



@require_http_methods(["GET", "POST"])
def set_password_view(request, token: str):
    tok = C.get_valid_token(token, kind="set_password")
    if not tok:
        return render(request, "control/set_password_invalid.html", status=400)

    if request.method == "POST":
        pwd = (request.POST.get("password") or "").strip()
        pwd2 = (request.POST.get("password2") or "").strip()
        if len(pwd) < 8:
            messages.error(request, "비밀번호는 8자 이상이어야 합니다.")
        elif pwd != pwd2:
            messages.error(request, "비밀번호 확인이 일치하지 않습니다.")
        else:
            C.set_user_password(tok["user_id"], make_password(pwd))
            C.mark_token_used(token)
            messages.success(request, "비밀번호가 설정되었습니다. 로그인해 주세요.")
            return redirect("login")
    return render(request, "control/set_password.html", {"token": token})

from django.views.decorators.http import require_GET

@require_GET
def logout_view(request):
    # 장고 세션 로그아웃 + 테넌트/그룹 관련 세션키도 정리
    logout(request)
    request.session.flush()
    return redirect("login")
