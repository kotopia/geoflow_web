from __future__ import annotations

from collections.abc import Iterable
from functools import wraps

from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.urls import reverse


GF_LOGIN_URL_NAME = "login"
GF_NO_PERM_URL_NAME = "no_perm"
_MISSING = object()


def _is_authenticated(request) -> bool:
    user = getattr(request, "user", None)
    return bool(user and getattr(user, "is_authenticated", False))


def _normalize_codes(value) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, Iterable):
        return set()
    return {str(code) for code in value if code}


def _cached_codes(request, *, attr_name: str, session_key: str) -> set[str]:
    """Read middleware-populated authorization data without querying the database.

    A request attribute is authoritative when it exists, including when it is empty.
    GFAuthzContextMiddleware deliberately writes empty request caches when central
    authorization refresh fails. Falling back to an older session value in that
    state would convert a fail-closed refresh into stale authorization.
    """

    value = getattr(request, attr_name, _MISSING)
    if value is not _MISSING:
        return _normalize_codes(value)

    session = getattr(request, "session", None)
    if session is None:
        return set()
    try:
        return _normalize_codes(session.get(session_key))
    except Exception:
        return set()


def gf_get_perms(request) -> set[str]:
    return _cached_codes(request, attr_name="_gf_perms_cache", session_key="gf_perms")


def gf_get_roles(request) -> set[str]:
    return _cached_codes(request, attr_name="_gf_roles_cache", session_key="gf_roles")


def gf_has_perm(request, perm_code: str) -> bool:
    """Return whether an authenticated request has one canonical permission."""

    if not _is_authenticated(request) or not perm_code:
        return False
    return str(perm_code) in gf_get_perms(request)


def gf_has_role(request, role_code: str) -> bool:
    """Return whether an authenticated request has one canonical role code."""

    if not _is_authenticated(request) or not role_code:
        return False
    return str(role_code) in gf_get_roles(request)


def gf_perm_required(*perm_codes, redirect_to_login=True, redirect_on_fail=False):
    """Require at least one permission code, preserving the legacy OR contract."""

    required = tuple(str(code) for code in perm_codes if code)

    def deco(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not _is_authenticated(request):
                if redirect_to_login:
                    return redirect(reverse(GF_LOGIN_URL_NAME))
                return HttpResponseForbidden("Authentication required")

            perms = gf_get_perms(request)
            if not perms:
                return HttpResponseForbidden("No permissions loaded")
            if required and any(code in perms for code in required):
                return view_func(request, *args, **kwargs)

            if redirect_on_fail:
                try:
                    return redirect(reverse(GF_NO_PERM_URL_NAME))
                except Exception:
                    pass
            return HttpResponseForbidden("Permission denied")

        return _wrapped

    return deco
