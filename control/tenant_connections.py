import logging

from django.conf import settings
from django.db import connections

from control.models import GroupDBConfig, UserGroupMap
from control.services_identity import ensure_user_from_request


logger = logging.getLogger(__name__)


def clear_tenant_session_state(request):
    central_alias = getattr(settings, "CENTRAL_DB_ALIAS", "default")
    request.session["tenant_db_alias"] = central_alias
    request.session["db_key"] = central_alias
    request.session.pop("group_uuid", None)
    request.session.pop("group_id", None)
    request.session.pop("roles", None)
    request.session.pop("tenant_candidates", None)


def ensure_tenant_connection_for_session(request):
    central_alias = getattr(settings, "CENTRAL_DB_ALIAS", "default")
    alias = request.session.get("tenant_db_alias")
    group_id = request.session.get("group_id")

    if not alias or alias == central_alias:
        return True
    if not group_id:
        return False
    if alias in connections.databases:
        return True

    user_id = ensure_user_from_request(request)
    if not user_id:
        return False

    try:
        is_authorized = (
            UserGroupMap.objects.using(central_alias)
            .filter(user_id=user_id, group_id=group_id, status="active")
            .exists()
        )
        if not is_authorized:
            return False

        config = (
            GroupDBConfig.objects.using(central_alias)
            .select_related("group")
            .filter(group_id=group_id, group__status="active")
            .first()
        )
    except Exception:
        logger.warning("Tenant connection configuration lookup failed")
        return False

    if not config or config.db_alias != alias:
        return False

    required_values = (
        config.db_name,
        config.db_host,
        config.db_port,
        config.db_user,
        config.db_password,
    )
    if any(value is None or not str(value).strip() for value in required_values):
        return False

    base_config = connections.databases.get(central_alias)
    if not base_config:
        return False

    db_config = dict(base_config)
    db_config.update(
        {
            "ENGINE": "django.contrib.gis.db.backends.postgis",
            "NAME": config.db_name,
            "USER": config.db_user,
            "PASSWORD": config.db_password,
            "HOST": config.db_host,
            "PORT": config.db_port,
            "OPTIONS": dict(base_config.get("OPTIONS", {})),
            "ATOMIC_REQUESTS": False,
            "CONN_MAX_AGE": 0,
            "CONN_HEALTH_CHECKS": False,
            "AUTOCOMMIT": True,
        }
    )

    settings.DATABASES[alias] = db_config
    connections.databases[alias] = db_config
    return True
