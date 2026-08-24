from __future__ import annotations

import logging
import os
import secrets

from django.conf import settings
from django.db import connections
from django.http import Http404, JsonResponse
from django.views.decorators.http import require_GET

from control.models import GroupDBConfig
from control.services.tenant_db_secret_resolver import (
    TenantDBCredentialError,
    resolve_tenant_db_password,
)

from .models import Contract


logger = logging.getLogger(__name__)

_ENABLED_VALUES = {"1", "true", "yes", "y", "on"}


def _enabled() -> bool:
    return os.getenv("TEMP_CONTRACT_LIST_API_ENABLED", "0").strip().lower() in _ENABLED_VALUES


def _configured_group_code() -> str:
    return os.getenv("TEMP_CONTRACT_LIST_GROUP_CODE", "").strip()


def _authorized(request) -> bool:
    expected = os.getenv("TEMP_CONTRACT_LIST_API_KEY", "").strip()
    provided = request.headers.get("X-GeoFlow-Temp-Key", "").strip()
    return bool(expected and provided and secrets.compare_digest(expected, provided))


def _connection_handler_can_resolve(alias: str) -> bool:
    try:
        if alias not in connections.settings:
            return False
        connections[alias]
    except Exception:
        logger.warning("Temporary contract-list tenant connection verification failed")
        return False
    return True


def _ensure_configured_tenant_connection() -> str:
    """Register the one tenant explicitly configured for this temporary API.

    The tenant is selected only from server-side environment configuration.
    Request parameters can never choose a tenant.
    """

    central_alias = getattr(settings, "CENTRAL_DB_ALIAS", "default")
    group_code = _configured_group_code()
    if not group_code:
        raise RuntimeError("Temporary contract-list tenant is not configured")

    config = (
        GroupDBConfig.objects.using(central_alias)
        .select_related("group")
        .filter(group__code=group_code, group__status="active")
        .first()
    )
    if not config:
        raise RuntimeError("Temporary contract-list tenant configuration was not found")

    alias = str(config.db_alias or "").strip()
    if not alias or alias == central_alias:
        raise RuntimeError("Temporary contract-list tenant alias is invalid")

    if _connection_handler_can_resolve(alias):
        return alias

    required_values = (
        config.db_name,
        config.db_host,
        config.db_port,
        config.db_user,
        config.db_password,
    )
    if any(value is None or not str(value).strip() for value in required_values):
        raise RuntimeError("Temporary contract-list tenant database configuration is incomplete")

    try:
        resolved_password = resolve_tenant_db_password(config.db_password)
    except TenantDBCredentialError as exc:
        raise RuntimeError("Temporary contract-list tenant credential resolution failed") from exc

    active_registry = connections.settings
    base_config = active_registry.get(central_alias)
    if not base_config:
        raise RuntimeError("Central database configuration is unavailable")

    db_config = dict(base_config)
    db_config.update(
        {
            "ENGINE": "django.contrib.gis.db.backends.postgis",
            "NAME": config.db_name,
            "USER": config.db_user,
            "PASSWORD": resolved_password,
            "HOST": config.db_host,
            "PORT": config.db_port,
            "OPTIONS": dict(base_config.get("OPTIONS", {})),
            "ATOMIC_REQUESTS": False,
            "CONN_MAX_AGE": 0,
            "CONN_HEALTH_CHECKS": False,
            "AUTOCOMMIT": True,
        }
    )

    settings_registry = settings.DATABASES
    active_registry[alias] = db_config
    if settings_registry is not active_registry:
        settings_registry[alias] = db_config

    if _connection_handler_can_resolve(alias):
        return alias

    active_registry.pop(alias, None)
    if settings_registry is not active_registry:
        settings_registry.pop(alias, None)
    try:
        del connections[alias]
    except Exception:
        pass
    raise RuntimeError("Temporary contract-list tenant connection could not be registered")


@require_GET
def contract_code_list(request):
    """Temporary, read-only contract-code list for Google Sheets integration.

    Response shape is intentionally a plain JSON list, e.g.
    ["2026-001", "2026-002"].

    This endpoint is isolated so it can be removed later without migrations or
    changes to the normal contract workflow.
    """

    if not _enabled():
        raise Http404

    if not _authorized(request):
        return JsonResponse({"detail": "Forbidden."}, status=403)

    try:
        alias = _ensure_configured_tenant_connection()
        codes = list(
            Contract.objects.using(alias)
            .exclude(code__isnull=True)
            .exclude(code="")
            .order_by("code")
            .values_list("code", flat=True)
            .distinct()
        )
    except Exception:
        logger.exception("Temporary contract-list API failed")
        return JsonResponse({"detail": "Temporary integration unavailable."}, status=503)

    response = JsonResponse(codes, safe=False, json_dumps_params={"ensure_ascii": False})
    response["Cache-Control"] = "no-store"
    return response
