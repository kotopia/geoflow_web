from django.conf import settings
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.contrib.auth import get_user_model, login, logout
from django.shortcuts import render, redirect
from django.http import HttpResponseForbidden
from django.db import connections
from django.contrib.auth.hashers import make_password
from django.urls import reverse
from control.services import central_repo as C
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.debug import (
    sensitive_post_parameters,
    sensitive_variables,
)
from django.middleware.csrf import rotate_token

from control.services.central_login_authentication import (
    PUBLIC_LOGIN_ERROR,
    CentralLoginPasswordConfigurationError,
    burn_central_login_password_check,
    verify_central_login_password,
)
from control.services.tenant_selection import (
    candidate_is_selectable as _candidate_is_selectable,
    configured_static_tenant_aliases as _configured_static_tenant_aliases,
    has_required_candidate_value as _has_required_candidate_value,
    selectable_tenant_candidates as _selectable_tenant_candidates,
    static_tenant_database_config_is_ready as _static_tenant_database_config_is_ready,
)
from control.tenant_connections import (
    clear_tenant_session_state,
    ensure_tenant_connection_for_session,
)

import logging
logger = logging.getLogger(__name__)


@sensitive_post_parameters("email", "username", "password")
@sensitive_variables("email", "pw", "pw_hash", "new_hash")
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

        # 1) 중앙 users에서 검증·승인된 활성 사용자/해시 조회
        with connections[central_alias].cursor() as cur:
            cur.execute("""
                SELECT id::text, password_hash, is_active
                  FROM users
                 WHERE lower(email) = lower(%s)
                   AND is_active = TRUE
                   AND email_verified = TRUE
                 LIMIT 1
            """, [email])
            row = cur.fetchone()

        if not row:
            burn_central_login_password_check(pw)
            return render(request, "control/login.html", {"error": PUBLIC_LOGIN_ERROR})

        user_uuid, pw_hash, is_active = row
        if is_active is not True:
            burn_central_login_password_check(pw)
            return render(request, "control/login.html", {"error": PUBLIC_LOGIN_ERROR})

        # 2) 비밀번호 검증(+구형 bcrypt → pbkdf2로 마이그레이션)
        try:
            password_result = verify_central_login_password(pw, pw_hash)
        except CentralLoginPasswordConfigurationError:
            logger.error("AUTH: central password verifier unavailable")
            return render(
                request,
                "control/login.html",
                {"error": PUBLIC_LOGIN_ERROR},
            )

        if not password_result.valid:
            return render(
                request,
                "control/login.html",
                {"error": PUBLIC_LOGIN_ERROR},
            )

        if password_result.needs_rehash:
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
        except Exception:
            logger.exception("AUTH: tenant lookup failed")
            tenants = []
        tenants = _selectable_tenant_candidates(user_uuid, tenants)

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
                logger.debug("AUTH: multiple tenant candidates")
                return redirect("control:group_search")
        else:
            # 소속 없음 → 중앙
            request.session["tenant_db_alias"] = central_alias
            logger.debug("AUTH: central route without tenant membership")
            return redirect("after_login")

    # GET
    return render(request, "control/login.html")


CENTRAL = getattr(settings, "CENTRAL_DB_ALIAS", "default")


def post_login_redirect(request):
    alias = request.session.get("tenant_db_alias")
    central_alias = getattr(settings, "CENTRAL_DB_ALIAS", "default")
    gid = request.session.get("group_id")

    if alias == central_alias or not gid:
        logger.debug("POST-LOGIN: route CENTRAL")
        return redirect('control:dashboard')  # 중앙 기본 홈

    if not ensure_tenant_connection_for_session(request):
        clear_tenant_session_state(request)
        logger.warning("POST-LOGIN: tenant connection unavailable")
        return redirect("control:dashboard")

    logger.debug("POST-LOGIN: route TENANT")
    return redirect("/")  # 테넌트 기본 홈



from django.views.decorators.http import require_GET

@require_GET
def logout_view(request):
    # 장고 세션 로그아웃 + 테넌트/그룹 관련 세션키도 정리
    logout(request)
    request.session.flush()
    return redirect("login")
