from __future__ import annotations

import os
import uuid
from functools import wraps
from types import SimpleNamespace

from django.conf import settings
from django.core import signing
from django.db import connections
from django.http import JsonResponse

from control.middleware import _set_threadlocal
from control.tenant_connections import ensure_tenant_connection_for_session


QFIELD_TICKET_SALT = "geoflow.gis.qfield.project-session.v1"
QFIELD_TICKET_MAX_AGE_SECONDS = 12 * 60 * 60
QFIELD_PACKAGE_IMPORT_SALT = "geoflow.gis.qfield.package-import.v1"
QFIELD_PACKAGE_IMPORT_MAX_AGE_SECONDS = 5 * 60


def qfield_ticket_runtime_enabled() -> bool:
    """Keep native-device bearer auth confined to the isolated GIS dev runtime.

    Production QField authentication needs a separately reviewed revocable
    device/session design. This ticket is for the current QField PoC only.
    """

    return bool(settings.DEBUG and os.getenv("GEOFLOW_DEV_RUNTIME_STRICT") == "1")


def _identity_payload(
    *,
    project_id: str,
    alias: str,
    group_id: str,
    user_id: str,
    email: str,
    roles,
    perms,
) -> dict:
    payload = {
        "project_id": str(uuid.UUID(str(project_id))),
        "alias": str(alias),
        "group_id": str(group_id),
        "user_id": str(user_id),
        "email": str(email or "").strip().lower(),
        "roles": sorted({str(value) for value in (roles or []) if str(value)}),
        "perms": sorted({str(value) for value in (perms or []) if str(value)}),
    }
    if not payload["alias"] or not payload["group_id"] or not payload["user_id"] or not payload["email"]:
        raise ValueError("QField ticket identity is incomplete")
    return payload


def issue_qfield_ticket(
    *,
    project_id: str,
    alias: str,
    group_id: str,
    user_id: str,
    email: str,
    roles,
    perms,
    write_authorized: bool,
) -> str:
    if not qfield_ticket_runtime_enabled():
        raise RuntimeError("QField project tickets are disabled outside strict development runtime")
    payload = _identity_payload(
        project_id=project_id,
        alias=alias,
        group_id=group_id,
        user_id=user_id,
        email=email,
        roles=roles,
        perms=perms,
    )
    payload["write_authorized"] = bool(write_authorized)
    return signing.dumps(payload, salt=QFIELD_TICKET_SALT, compress=True)


def issue_qfield_package_import_token(
    *,
    project_id: str,
    alias: str,
    group_id: str,
    user_id: str,
    email: str,
    roles,
    perms,
) -> str:
    """Issue a purpose-limited URL token for QField's native import flow.

    QField's qfield://local?import=... handoff fetches the ZIP itself and cannot
    reuse the browser session cookie.  This short-lived token authorizes only
    package materialization; the imported project receives its own normal
    project-scoped QField bearer ticket.
    """

    if not qfield_ticket_runtime_enabled():
        raise RuntimeError("QField package links are disabled outside strict development runtime")
    payload = _identity_payload(
        project_id=project_id,
        alias=alias,
        group_id=group_id,
        user_id=user_id,
        email=email,
        roles=roles,
        perms=perms,
    )
    payload["purpose"] = "qfield_package_import"
    return signing.dumps(payload, salt=QFIELD_PACKAGE_IMPORT_SALT, compress=True)


def _parse_identity_token(token: str, *, project_id: str, salt: str, max_age: int) -> dict | None:
    if not token or not qfield_ticket_runtime_enabled():
        return None
    try:
        payload = signing.loads(token, salt=salt, max_age=max_age)
    except (signing.BadSignature, signing.SignatureExpired):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        expected = str(uuid.UUID(str(project_id)))
        actual = str(uuid.UUID(str(payload.get("project_id"))))
    except (TypeError, ValueError, AttributeError):
        return None
    if expected != actual:
        return None
    required = ("alias", "group_id", "user_id", "email")
    if any(not str(payload.get(key) or "") for key in required):
        return None
    return payload


def parse_qfield_ticket(token: str, *, project_id: str) -> dict | None:
    return _parse_identity_token(
        token,
        project_id=project_id,
        salt=QFIELD_TICKET_SALT,
        max_age=QFIELD_TICKET_MAX_AGE_SECONDS,
    )


def parse_qfield_package_import_token(token: str, *, project_id: str) -> dict | None:
    payload = _parse_identity_token(
        token,
        project_id=project_id,
        salt=QFIELD_PACKAGE_IMPORT_SALT,
        max_age=QFIELD_PACKAGE_IMPORT_MAX_AGE_SECONDS,
    )
    if payload is None or payload.get("purpose") != "qfield_package_import":
        return None
    return payload


def bearer_token_from_request(request) -> str:
    value = str(request.headers.get("Authorization") or "").strip()
    prefix = "bearer "
    if value.lower().startswith(prefix):
        return value[len(prefix):].strip()
    return ""


def _central_membership_valid(payload: dict) -> bool:
    central_alias = getattr(settings, "CENTRAL_DB_ALIAS", "default")
    try:
        with connections[central_alias].cursor() as cursor:
            cursor.execute(
                """
                SELECT 1
                  FROM users u
                  JOIN user_group_map ugm ON ugm.user_id=u.id
                  JOIN groups g ON g.id=ugm.group_id
                  JOIN group_db_config cfg ON cfg.group_id=g.id
                 WHERE lower(u.email)=lower(%s)
                   AND u.is_active=TRUE
                   AND u.email_verified=TRUE
                   AND ugm.group_id=%s
                   AND ugm.status='active'
                   AND g.status='active'
                   AND cfg.db_alias=%s
                 LIMIT 1
                """,
                [
                    str(payload.get("email") or ""),
                    str(payload.get("group_id") or ""),
                    str(payload.get("alias") or ""),
                ],
            )
            return cursor.fetchone() is not None
    except Exception:
        return False


def _hydrate_identity_request(request, payload: dict) -> dict | None:
    if not _central_membership_valid(payload):
        return None

    alias = str(payload["alias"])
    group_id = str(payload["group_id"])
    request.session["tenant_db_alias"] = alias
    request.session["db_key"] = alias
    request.session["group_id"] = group_id
    request.session["group_uuid"] = group_id
    request.session["scope"] = "tenant"
    request.session["gf_roles"] = list(payload.get("roles") or [])
    request.session["gf_perms"] = list(payload.get("perms") or [])
    request._gf_roles_cache = set(payload.get("roles") or [])
    request._gf_perms_cache = set(payload.get("perms") or [])
    request.user = SimpleNamespace(
        pk=str(payload["user_id"]),
        email=str(payload["email"]),
        username=str(payload["email"]),
        is_authenticated=True,
        is_active=True,
    )

    if not ensure_tenant_connection_for_session(request):
        return None
    _set_threadlocal(alias, False, group_id)
    return payload


def hydrate_qfield_ticket_request(request, *, project_id: str, require_write: bool = False) -> dict | None:
    token = bearer_token_from_request(request)
    payload = parse_qfield_ticket(token, project_id=project_id)
    if payload is None:
        return None
    if require_write and not bool(payload.get("write_authorized")):
        return None
    payload = _hydrate_identity_request(request, payload)
    if payload is None:
        return None
    request._qfield_ticket_payload = payload
    return payload


def hydrate_qfield_package_import_request(request, *, project_id: str) -> dict | None:
    payload = parse_qfield_package_import_token(
        str(request.GET.get("token") or ""),
        project_id=project_id,
    )
    if payload is None:
        return None
    payload = _hydrate_identity_request(request, payload)
    if payload is None:
        return None
    request._qfield_package_import_payload = payload
    return payload


def qfield_session_or_ticket_required(view_func):
    """Allow the existing browser/QGIS session path or a valid QField ticket."""

    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            return view_func(request, *args, **kwargs)
        project_id = kwargs.get("project_id")
        if project_id and hydrate_qfield_ticket_request(request, project_id=str(project_id)):
            return view_func(request, *args, **kwargs)
        return JsonResponse({"ok": False, "error": "qfield_auth_required"}, status=401)

    return wrapped


def qfield_ticket_required(*, write: bool = False):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            project_id = kwargs.get("project_id")
            payload = None
            if project_id:
                payload = hydrate_qfield_ticket_request(
                    request,
                    project_id=str(project_id),
                    require_write=write,
                )
            if payload is None:
                return JsonResponse({"ok": False, "error": "invalid_qfield_ticket"}, status=401)
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator
