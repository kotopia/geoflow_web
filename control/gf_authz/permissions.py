from __future__ import annotations

from collections.abc import Iterable


_PRIVILEGED_ROLES = {"OWNER", "ADMIN"}
_MISSING = object()


def _is_authenticated(request) -> bool:
    user = getattr(request, "user", None)
    return bool(user and getattr(user, "is_authenticated", False))


def _is_superuser(request) -> bool:
    user = getattr(request, "user", None)
    return bool(user and getattr(user, "is_superuser", False))


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

    The request attribute is authoritative when it exists, including when it is an
    empty set. This matters because GFAuthzContextMiddleware deliberately writes an
    empty cache when central authorization refresh fails; falling back to an older
    session value in that case would turn a fail-closed refresh into stale access.
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


def _roles(request) -> set[str]:
    return _cached_codes(request, attr_name="_gf_roles_cache", session_key="gf_roles")


def _permissions(request) -> set[str]:
    return _cached_codes(request, attr_name="_gf_perms_cache", session_key="gf_perms")


def gf_has_perm(request, perm: str) -> bool:
    """Return whether the authenticated request has one canonical permission.

    Authorization context is loaded once per request by GFAuthzContextMiddleware.
    This helper intentionally performs no database fallback: missing or failed
    authorization context must deny access rather than silently changing identity or
    tenant scope.
    """

    if not _is_authenticated(request) or not perm:
        return False
    if _is_superuser(request):
        return True
    if _roles(request) & _PRIVILEGED_ROLES:
        return True
    return str(perm) in _permissions(request)


def gf_has_role(request, role: str) -> bool:
    """Return whether the authenticated request has one canonical role code."""

    if not _is_authenticated(request) or not role:
        return False
    if _is_superuser(request):
        return True
    return str(role) in _roles(request)
