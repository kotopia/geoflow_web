# control/middleware.py
from __future__ import annotations
from typing import Optional
import threading

from django.utils.deprecation import MiddlewareMixin
from django.conf import settings
from django.http import HttpRequest, HttpResponse

import logging
logger = logging.getLogger(__name__)

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

        # ✅ /control/ 진입은 무조건 중앙으로
        if path.startswith("/control/"):
            _set_threadlocal(central_alias, True, None)
            request.session["tenant_db_alias"] = central_alias
            request.session["scope"] = "central"     # ✅ 추가
            logger.info("MW: force-central path=%s alias=%s", path, central_alias)
            return self.get_response(request)

        # 세션이 있으면 사용, 없으면 중앙
        alias = request.session.get("tenant_db_alias") or central_alias
        _set_threadlocal(alias, alias == central_alias, request.session.get("group_id"))
        request.session["tenant_db_alias"] = alias
        request.session["scope"] = "central" if alias == central_alias else "tenant"  # ✅ 추가

        logger.info("MW: resolved alias=%s is_central=%s path=%s", alias, alias == central_alias, path)
        return self.get_response(request)



class EnsureTenantAliasMiddleware:
    """
    C) 뷰 실행 직전/직후 alias가 비어 있지 않은지 보증(보정).
    위 TenantMiddleware가 거의 다 처리하지만, 예외 경로 대비용 안전망.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if not getattr(_tlocal, "tenant_db_alias", None):
            central_alias = getattr(settings, "CENTRAL_DB_ALIAS", "default")
            alias = request.session.get("tenant_db_alias") or getattr(settings, "DEFAULT_TENANT_DB_ALIAS", central_alias)
            _set_threadlocal(alias, alias == central_alias)

            try:
                request.session["tenant_db_alias"] = alias
            except Exception:
                pass

        response = self.get_response(request)
        return response


TENANT_PATH_PREFIXES = (
    '/',              # 루트가 테넌트 홈인 구조라면 포함
    '/employees', '/contracts', '/partners', '/projects', '/maps',
)

class TenantSelectorMiddleware(MiddlewareMixin):
    """요청마다 alias를 세팅. /control/ 는 항상 중앙으로."""
    def process_request(self, request):
        central = getattr(settings, "CENTRAL_DB_ALIAS", "default")

        if request.path.startswith('/control/'):
            request.session['scope'] = 'central'
            request.session['tenant_db_alias'] = central
            logger.info("MW: force-central path=%s alias=%s", request.path, central)
            return None

        # 세션에 alias 없으면 중앙을 기본으로(런타임 기본=중앙)
        alias = request.session.get('tenant_db_alias') or central
        request.session['tenant_db_alias'] = alias
        request.session['scope'] = 'tenant' if alias != central else 'central'
        logger.info("MW: resolved alias=%s is_central=%s path=%s",
                    alias, alias == central, request.path)
        return None
    

class CentralGuardMiddleware(MiddlewareMixin):
    """중앙 상태에서 테넌트 URL 접근을 /control/ 로 리디렉트."""
    def process_request(self, request):
        central = getattr(settings, "CENTRAL_DB_ALIAS", "default")
        alias = request.session.get('tenant_db_alias') or central

        # 로그인/정적/중앙 경로는 패스
        if request.path.startswith(('/login', '/logout', '/after-login', '/control/', '/static/', '/media/')):
            return None

        # 중앙이면 테넌트 URL로 못 가게
        if alias == central:
            for pre in TENANT_PATH_PREFIXES:
                # 루트('/')는 정확 판별
                if pre == '/' and request.path == '/':
                    logger.info("CENTRAL_GUARD: redirect %s -> /control/", request.path)
                    from django.shortcuts import redirect
                    return redirect('control:dashboard')
                if pre != '/' and (request.path == pre or request.path.startswith(pre + '/')):
                    logger.info("CENTRAL_GUARD: redirect %s -> /control/", request.path)
                    from django.shortcuts import redirect
                    return redirect('control:dashboard')
        return None