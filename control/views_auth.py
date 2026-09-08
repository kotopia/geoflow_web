import logging
import os

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

logger = logging.getLogger(__name__)


def _dev_auth_diag_enabled():
    return (
        getattr(settings, "DEBUG", False)
        and os.getenv("GEOFLOW_DEV_RUNTIME_STRICT") == "1"
        and os.getenv("GEOFLOW_DEV_AUTH_DIAGNOSTICS") == "1"
    )


def _dev_auth_diag(stage, **fields):
    if not _dev_auth_diag_enabled():
        return
    safe = " ".join(f"{key}={value}" for key, value in fields.items())
    logger.warning("DEV-AUTH %s%s", stage, f" {safe}" if safe else "")


@sensitive_post_parameters("email", "username", "password")
@sensitive_variables("email", "pw", "pw_hash", "new_hash")
@require_http_methods(["GET", "POST"])
@csrf_protect
@ensure_csrf_cookie
def login_view(request):

    if request.user.is_authenticated:
        return redirect("after_login")

    if request.method == "GET":
        logout(request)
        request.session.flush()

    if request.method == "POST":
        email = (request.POST.get("email") or request.POST.get("username") or "").strip().lower()
        pw = (request.POST.get("password") or "")
        _dev_auth_diag("POST_RECEIVED", email=email, password_length=len(pw))

        if not email or not pw:
            _dev_auth_diag("MISSING_CREDENTIAL_FIELD")
            return render(request, "control/login.html", {"error": "이메일/비밀번호를 입력하세요."})

        central_alias = getattr(settings, "CENTRAL_DB_ALIAS", "default")

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
            _dev_auth_diag("USER_LOOKUP_FAIL", central_alias=central_alias)
            burn_central_login_password_check(pw)
            return render(request, "control/login.html", {"error": PUBLIC_LOGIN_ERROR})

        user_uuid, pw_hash, is_active = row
        _dev_auth_diag("USER_FOUND", user_uuid=user_uuid, central_alias=central_alias)
        if is_active is not True:
            _dev_auth_diag("USER_INACTIVE", user_uuid=user_uuid)
            burn_central_login_password_check(pw)
            return render(request, "control/login.html", {"error": PUBLIC_LOGIN_ERROR})

        try:
            password_result = verify_central_login_password(pw, pw_hash)
        except CentralLoginPasswordConfigurationError:
            logger.error("AUTH: central password verifier unavailable")
            _dev_auth_diag("PASSWORD_VERIFIER_UNAVAILABLE", user_uuid=user_uuid)
            return render(
                request,
                "control/login.html",
                {"error": PUBLIC_LOGIN_ERROR},
            )

        if not password_result.valid:
            _dev_auth_diag("PASSWORD_FAIL", user_uuid=user_uuid, password_length=len(pw))
            return render(
                request,
                "control/login.html",
                {"error": PUBLIC_LOGIN_ERROR},
            )

        _dev_auth_diag("PASSWORD_OK", user_uuid=user_uuid, needs_rehash=password_result.needs_rehash)
        if password_result.needs_rehash:
            new_hash = make_password(pw)
            with connections[central_alias].cursor() as cur:
                cur.execute(
                    "UPDATE users SET password_hash=%s, updated_at=now() WHERE id=%s",
                    [new_hash, user_uuid],
                )

        User = get_user_model()
        u, created = User.objects.get_or_create(username=email, defaults={"email": email, "is_active": True})
        _dev_auth_diag("SESSION_BRIDGE_READY", auth_user_id=u.pk, created=created)
        u.backend = "django.contrib.auth.backends.ModelBackend"
        login(request, u)
        rotate_token(request)
        _dev_auth_diag("SESSION_LOGIN_OK", auth_user_id=u.pk)

        central_alias = getattr(settings, "CENTRAL_DB_ALIAS", "default")

        try:
            tenants = C.list_tenants_for_user(user_uuid)
        except Exception:
            logger.exception("AUTH: tenant lookup failed")
            _dev_auth_diag("TENANT_LOOKUP_EXCEPTION", user_uuid=user_uuid)
            tenants = []
        _dev_auth_diag("TENANT_CANDIDATES_RAW", count=len(tenants))
        tenants = _selectable_tenant_candidates(user_uuid, tenants)
        _dev_auth_diag("TENANT_CANDIDATES_SELECTABLE", count=len(tenants))

        if tenants:
            if len(tenants) == 1:
                t = tenants[0]
                request.session["group_uuid"] = t["id"]
                request.session["group_id"] = t["id"]
                request.session["tenant_db_alias"] = t["db_alias"]
                request.session["db_key"] = t["db_alias"]

                try:
                    roles = C.list_roles_for_user_in_group(user_uuid, t["id"])
                except Exception:
                    roles = []

                request.session["roles"] = roles
                _dev_auth_diag("TENANT_SELECTED", group_id=t["id"], db_alias=t["db_alias"], roles=len(roles))
                return redirect("after_login")
            else:
                request.session["tenant_candidates"] = tenants
                logger.debug("AUTH: multiple tenant candidates")
                _dev_auth_diag("MULTIPLE_TENANTS", count=len(tenants))
                return redirect("control:group_search")
        else:
            request.session["tenant_db_alias"] = central_alias
            logger.debug("AUTH: central route without tenant membership")
            _dev_auth_diag("NO_SELECTABLE_TENANT")
            return redirect("after_login")

    return render(request, "control/login.html")


CENTRAL = getattr(settings, "CENTRAL_DB_ALIAS", "default")


def post_login_redirect(request):
    alias = request.session.get("tenant_db_alias")
    central_alias = getattr(settings, "CENTRAL_DB_ALIAS", "default")
    gid = request.session.get("group_id")

    if alias == central_alias or not gid:
        logger.debug("POST-LOGIN: route CENTRAL")
        _dev_auth_diag("POST_LOGIN_ROUTE_CENTRAL", alias=alias, group_id=gid)
        return redirect('control:dashboard')

    if not ensure_tenant_connection_for_session(request):
        clear_tenant_session_state(request)
        logger.warning("POST-LOGIN: tenant connection unavailable")
        _dev_auth_diag("POST_LOGIN_TENANT_CONNECTION_FAIL", alias=alias, group_id=gid)
        return redirect("control:dashboard")

    logger.debug("POST-LOGIN: route TENANT")
    _dev_auth_diag("POST_LOGIN_ROUTE_TENANT", alias=alias, group_id=gid)
    return redirect("/")


from django.views.decorators.http import require_GET

@require_GET
def logout_view(request):
    logout(request)
    request.session.flush()
    return redirect("login")
