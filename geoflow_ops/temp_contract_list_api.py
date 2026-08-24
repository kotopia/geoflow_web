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

from .models import Contract, Project


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


def _project_payload(project: Project) -> dict:
    return {
        "id": project.id,
        "code": project.code,
        "name": project.name,
        "start_date": project.start_date,
        "end_date": project.end_date,
        "status": project.status,
        "description": project.description,
        "org_unit_id": project.org_unit_id,
        "ext": project.ext,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }


def _contract_payload(contract: Contract, projects: list[Project]) -> dict:
    primary_project = projects[0] if projects else None
    return {
        "contract_id": contract.id,
        "legacy_id": contract.legacy_id,
        "contract_code": contract.code,
        "contract_name": contract.name,
        "project_id": primary_project.id if primary_project else None,
        "project_code": primary_project.code if primary_project else None,
        "project_name": primary_project.name if primary_project else None,
        "project_codes": [project.code for project in projects if project.code],
        "start_date": contract.start_date,
        "end_date": contract.end_date,
        "amount": contract.amount,
        "status": contract.status,
        "kind": contract.kind,
        "division": contract.division,
        "client_id": contract.client_id,
        "client_name": contract.client.name if contract.client_id and contract.client else None,
        "sub_client_id": contract.sub_client_id,
        "sub_client_name": (
            contract.sub_client.name
            if contract.sub_client_id and contract.sub_client
            else None
        ),
        "org_unit_id": contract.org_unit_id,
        "org_unit_name": (
            contract.org_unit.name
            if contract.org_unit_id and contract.org_unit
            else None
        ),
        "description": contract.description,
        "ext": contract.ext,
        "created_at": contract.created_at,
        "updated_at": contract.updated_at,
        "projects": [_project_payload(project) for project in projects],
    }


@require_GET
def contract_list(request):
    """Temporary, read-only full contract list for Google Sheets integration.

    The response is a JSON array. Each row contains all fields represented by
    the tenant Contract model, friendly names for related client/org records,
    the primary project code/name for flat spreadsheet use, and the complete
    related project list for compatibility with legacy contracts that may have
    more than one project.

    This endpoint is isolated so it can be removed later without migrations or
    changes to the normal contract workflow.
    """

    if not _enabled():
        raise Http404

    if not _authorized(request):
        return JsonResponse({"detail": "Forbidden."}, status=403)

    try:
        alias = _ensure_configured_tenant_connection()
        contracts = list(
            Contract.objects.using(alias)
            .select_related("client", "sub_client", "org_unit")
            .order_by("code", "name", "id")
        )

        contract_ids = [contract.id for contract in contracts]
        projects_by_contract: dict = {contract_id: [] for contract_id in contract_ids}
        if contract_ids:
            projects = (
                Project.objects.using(alias)
                .filter(contract_id__in=contract_ids)
                .order_by("contract_id", "code", "name", "id")
            )
            for project in projects:
                projects_by_contract.setdefault(project.contract_id, []).append(project)

        rows = [
            _contract_payload(contract, projects_by_contract.get(contract.id, []))
            for contract in contracts
        ]
    except Exception:
        logger.exception("Temporary contract-list API failed")
        return JsonResponse({"detail": "Temporary integration unavailable."}, status=503)

    response = JsonResponse(rows, safe=False, json_dumps_params={"ensure_ascii": False})
    response["Cache-Control"] = "no-store"
    return response
