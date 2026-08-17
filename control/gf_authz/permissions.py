from functools import wraps
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.urls import reverse

GF_LOGIN_URL_NAME = "login"
GF_NO_PERM_URL_NAME = "no_perm"


def gf_get_perms(request):
    cached_perms = getattr(request, "_gf_perms_cache", None)
    if cached_perms is not None:
        return set(cached_perms)
    return set(request.session.get("gf_perms") or [])


def gf_get_roles(request):
    cached_roles = getattr(request, "_gf_roles_cache", None)
    if cached_roles is not None:
        return set(cached_roles)
    return set(request.session.get("gf_roles") or [])


def gf_has_perm(request, perm_code: str) -> bool:
    return perm_code in gf_get_perms(request)


def gf_has_role(request, role_code: str) -> bool:
    return role_code in gf_get_roles(request)


def _project_scope_override(request, perm_codes, args, kwargs) -> bool:
    """Bridge reviewed project-scoped authorization to legacy decorators.

    Project routes now authorize an exact project id before entering older view
    functions that still carry ``projects.view/edit`` decorators. This override
    is deliberately request-local and exact-id scoped; it never grants a tenant-
    wide permission or applies when the route did not establish the boundary.
    """

    scope = getattr(request, "_gf_project_scope_authorized", None)
    if not isinstance(scope, dict):
        return False
    project_id = kwargs.get("pk")
    if project_id is None and args:
        project_id = args[0]
    if not project_id or str(project_id) != str(scope.get("project_id") or ""):
        return False

    codes = set(perm_codes)
    if "projects.edit" in codes:
        return bool(scope.get("write"))
    if "projects.view" in codes:
        return bool(scope.get("read") or scope.get("write"))
    return False


def gf_perm_required(*perm_codes, redirect_to_login=True, redirect_on_fail=False):
    """OR 조건: perm_codes 중 하나라도 있으면 통과."""

    def deco(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                if redirect_to_login:
                    return redirect(reverse(GF_LOGIN_URL_NAME))
                return HttpResponseForbidden("Authentication required")

            if _project_scope_override(request, perm_codes, args, kwargs):
                return view_func(request, *args, **kwargs)

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
