from functools import wraps
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.urls import reverse

GF_LOGIN_URL_NAME = "login"       # 기존 로그인 url name 재사용
GF_NO_PERM_URL_NAME = "no_perm"   # 없으면 403을 그대로 응답

def gf_get_perms(request):
    return set(getattr(request, "_gf_perms_cache", None) or request.session.get("gf_perms") or [])

def gf_get_roles(request):
    return set(getattr(request, "_gf_roles_cache", None) or request.session.get("gf_roles") or [])

def gf_has_perm(request, perm_code: str) -> bool:
    return perm_code in gf_get_perms(request)

def gf_has_role(request, role_code: str) -> bool:
    return role_code in gf_get_roles(request)

def gf_perm_required(*perm_codes, redirect_to_login=True, redirect_on_fail=False):
    """OR 조건: perm_codes 중 하나라도 있으면 통과"""
    def deco(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                if redirect_to_login:
                    return redirect(reverse(GF_LOGIN_URL_NAME))
                return HttpResponseForbidden("Authentication required")
            perms = gf_get_perms(request)
            if not perms:
                return HttpResponseForbidden("No permissions loaded")
            if any(code in perms for code in perm_codes):
                return view_func(request, *args, **kwargs)
            if redirect_on_fail:
                try:
                    return redirect(reverse(GF_NO_PERM_URL_NAME))
                except Exception:
                    pass
            return HttpResponseForbidden("Permission denied")
        return _wrapped
    return deco
