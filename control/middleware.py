# control/middleware.py
from __future__ import annotations
from typing import Optional
import threading

from django.utils.deprecation import MiddlewareMixin
from django.conf import settings
from django.contrib.auth import logout
from django.db import connections
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect

from control.tenant_connections import (
    clear_tenant_authorization_cache,
    clear_tenant_session_state,
    ensure_tenant_connection_for_session,
)

import logging
logger = logging.getLogger(__name__)


class CentralAccountActiveGuardMiddleware:
    """Fail closed when an authenticated central account is not active."""

    PUBLIC_EXACT_PATHS = {
        "/login",
        "/login/",
        "/signup",
        "/signup/",
        "/control/signup",
        "/control/signup/",
        "/control/logout",
        "/control/logout/",
        "/admin",
        "/admin/",
        "/health",
        "/health/",
        "/check",
        "/check/",
    }
    PUBLIC_PATH_PREFIXES = (
        "/admin/",
        "/signup/",
        "/static/",
        "/media/",
        "/health/",
        "/check/",
        "/control/set-password/",
        "/control/account/set-password/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    @classmethod
    def _is_public_path(cls, path):
        return path in cls.PUBLIC_EXACT_PATHS or any(
            path.startswith(prefix) for prefix in cls.PUBLIC_PATH_PREFIXES
        )

    @staticmethod
    def _is_api_request(request):
        accept = request.headers.get("Accept", "").lower()
        requested_with = request.headers.get("X-Requested-With", "").lower()
        return (
            request.path.startswith("/api/")
            or "application/json" in accept
            or requested_with == "xmlhttprequest"
        )

    @staticmethod
    def _central_account_is_active(request):
        user = request.user
        email = (
            getattr(user, "email", None)
            or getattr(user, "username", None)
            or ""
        ).strip().lower()
        if not email:
            return False

        central_alias = getattr(settings, "CENTRAL_DB_ALIAS", "default")
        with connections[central_alias].cursor() as cur:
            cur.execute(
                """
                SELECT is_active
                  FROM users
                 WHERE lower(email) = lower(%s)
                 LIMIT 1
                """,
                [email],
            )
            row = cur.fetchone()
        return bool(row and row[0] is True)

    def __call__(self, request: HttpRequest) -> HttpResponse:
        path = request.path or "/"
        if self._is_public_path(path):
            return self.get_response(request)

        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return self.get_response(request)

        try:
            is_active = self._central_account_is_active(request)
        except Exception:
            logger.warning("Central account active lookup failed")
            is_active = False

        if is_active:
            return self.get_response(request)

        is_api_request = self._is_api_request(request)
        logout(request)
        if is_api_request:
            return JsonResponse({"detail": "Authentication required."}, status=401)
        return redirect("login")


class TenantMembershipFreshnessGuardMiddleware:
    """Fail closed when a tenant session is no longer centrally authorized."""

    EXEMPT_EXACT_PATHS = {
        "/login",
        "/login/",
        "/signup",
        "/signup/",
        "/control/signup",
        "/control/signup/",
        "/control/logout",
        "/control/logout/",
        "/admin",
        "/admin/",
        "/health",
        "/health/",
        "/check",
        "/check/",
    }
    EXEMPT_PATH_PREFIXES = (
        "/admin/",
        "/control/",
        "/signup/",
        "/static/",
        "/media/",
        "/health/",
        "/check/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    @classmethod
    def _is_exempt_path(cls, path):
        return path in cls.EXEMPT_EXACT_PATHS or any(
            path.startswith(prefix) for prefix in cls.EXEMPT_PATH_PREFIXES
        )

    @staticmethod
    def _is_api_request(request):
        accept = request.headers.get("Accept", "").lower()
        requested_with = request.headers.get("X-Requested-With", "").lower()
        return (
            request.path.startswith("/api/")
            or "application/json" in accept
            or requested_with == "xmlhttprequest"
        )

    @staticmethod
    def _membership_is_current(request, group_id, tenant_alias):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False

        email = (
            getattr(user, "email", None)
            or getattr(user, "username", None)
            or ""
        ).strip().lower()
        if not email:
            return False

        central_alias = getattr(settings, "CENTRAL_DB_ALIAS", "default")
        with connections[central_alias].cursor() as cur:
            cur.execute(
                """
                SELECT 1
                  FROM users u
                  JOIN user_group_map ugm ON ugm.user_id = u.id
                  JOIN groups g ON g.id = ugm.group_id
                  JOIN group_db_config cfg ON cfg.group_id = g.id
                 WHERE lower(u.email) = lower(%s)
                   AND u.is_active = TRUE
                   AND ugm.group_id = %s
                   AND ugm.status = 'active'
                   AND g.status = 'active'
                   AND cfg.db_alias = %s
                 LIMIT 1
                """,
                [email, str(group_id), tenant_alias],
            )
            return cur.fetchone() is not None

    def __call__(self, request: HttpRequest) -> HttpResponse:
        path = request.path or "/"
        if self._is_exempt_path(path):
            return self.get_response(request)

        central_alias = getattr(settings, "CENTRAL_DB_ALIAS", "default")
        tenant_alias = request.session.get("tenant_db_alias")
        if not tenant_alias or tenant_alias == central_alias:
            return self.get_response(request)

        group_id = request.session.get("group_id") or request.session.get(
            "group_uuid"
        )
        try:
            is_current = bool(group_id) and self._membership_is_current(
                request,
                group_id,
                tenant_alias,
            )
        except Exception:
            logger.warning("Tenant membership freshness lookup failed")
            is_current = False

        if is_current:
            clear_tenant_authorization_cache(request)
            return self.get_response(request)

        is_api_request = self._is_api_request(request)
        clear_tenant_session_state(request)
        request.session.pop("tenant_db_alias", None)
        request.session.pop("db_key", None)
        if is_api_request:
            return JsonResponse({"detail": "Tenant access denied."}, status=403)
        return redirect("control:dashboard")

# ── 스레드 로컬에 현재 요청의 테넌트 정보를 보관
_tlocal = threading.local()

def _set_threadlocal(tenant_alias: str | None, is_central: bool, tenant_id: str | None = None):
    _tlocal.tenant_db_alias = tenant_alias
    _tlocal.is_central = is_central
    _tlocal.tenant_id = tenant_id

def current_db_alias(default: Optional[str] = None) -> str:
    """
    런타임 기본은 '중앙'. DEFAULT_TENANT_DB_ALIAS는 마이그레이션/초기화 용도에만 사용.
    """
    alias = getattr(_tlocal, "tenant_db_alias", None)
    if alias:
        return alias
    # ✅ 기본이 'CENTRAL_DB_ALIAS'
    return default or getattr(settings, "CENTRAL_DB_ALIAS", "default")

def is_central_request() -> bool:
    return bool(getattr(_tlocal, "is_central", False))

def get_current_tenant() -> Optional[str]:
    """
    템플릿 태그 등에서 사용 가능. 테넌트 식별자(있다면)를 반환.
    """
    return getattr(_tlocal, "tenant_id", None)

class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        path = request.path or "/"
        central_alias = getattr(settings, "CENTRAL_DB_ALIAS", "default")

        if path.startswith(("/login/", "/signup/", "/static/", "/media/")):
            _set_threadlocal(central_alias, True, None)
            request.session["scope"] = "central"
            return self.get_response(request)

        # ✅ /control/ 진입은 무조건 중앙으로
        if path.startswith("/control/"):
            _set_threadlocal(central_alias, True, None)
            request.session["tenant_db_alias"] = central_alias
            request.session["scope"] = "central"     # ✅ 추가
            logger.debug("MW: resolved central route")
            return self.get_response(request)

        # 세션이 있으면 사용, 없으면 중앙
        alias = request.session.get("tenant_db_alias") or central_alias
        if alias != central_alias and not ensure_tenant_connection_for_session(request):
            clear_tenant_session_state(request)
            _set_threadlocal(central_alias, True, None)
            request.session["scope"] = "central"
            logger.warning("MW: tenant connection unavailable")
            return redirect("control:dashboard")

        _set_threadlocal(alias, alias == central_alias, request.session.get("group_id"))
        request.session["tenant_db_alias"] = alias
        request.session["scope"] = "central" if alias == central_alias else "tenant"  # ✅ 추가

        logger.debug(
            "MW: resolved central route"
            if alias == central_alias
            else "MW: resolved tenant route"
        )
        return self.get_response(request)



class EnsureTenantAliasMiddleware:
    """
    Compatibility pass-through.
    TenantMiddleware owns connection preparation and request-local context.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        return self.get_response(request)


TENANT_PATH_PREFIXES = (
    '/',              # 루트가 테넌트 홈인 구조라면 포함
    '/employees', '/contracts', '/partners', '/projects', '/maps',
)

class CentralGuardMiddleware(MiddlewareMixin):
    """중앙 상태에서 테넌트 URL 접근을 /control/ 로 리디렉트."""
    def process_request(self, request):
        central = getattr(settings, "CENTRAL_DB_ALIAS", "default")
        alias = request.session.get('tenant_db_alias') or central

        # 로그인/정적/중앙 경로는 패스
        if request.path.startswith(
            (
                '/login', '/logout', '/after-login', '/signup',
                '/control/', '/static/', '/media/',
            )
        ):
            return None

        # 중앙이면 테넌트 URL로 못 가게
        if alias == central:
            for pre in TENANT_PATH_PREFIXES:
                # 루트('/')는 정확 판별
                if pre == '/' and request.path == '/':
                    logger.debug("CENTRAL_GUARD: redirect to central route")
                    from django.shortcuts import redirect
                    return redirect('control:dashboard')
                if pre != '/' and (request.path == pre or request.path.startswith(pre + '/')):
                    logger.debug("CENTRAL_GUARD: redirect to central route")
                    from django.shortcuts import redirect
                    return redirect('control:dashboard')
        return None
