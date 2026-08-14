from __future__ import annotations

import logging

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist

from control.models import UserGroupMap
from control.services import central_repo as C


logger = logging.getLogger(__name__)


def has_required_candidate_value(value):
    return value is not None and bool(str(value).strip())


def configured_static_tenant_aliases():
    """Return aliases intentionally configured as static tenant databases."""

    configured = getattr(settings, "STATIC_TENANT_DB_ALIASES", None)
    if configured is None:
        configured = (getattr(settings, "DEFAULT_TENANT_DB_ALIAS", None),)
    elif isinstance(configured, str):
        configured = (configured,)

    return {
        str(alias).strip()
        for alias in configured
        if alias is not None and str(alias).strip()
    }


def static_tenant_database_config_is_ready(alias):
    alias = str(alias or "").strip()
    central_alias = str(
        getattr(settings, "CENTRAL_DB_ALIAS", "default") or "default"
    ).strip()
    if not alias or alias == central_alias:
        return False
    if alias not in configured_static_tenant_aliases():
        return False

    databases = getattr(settings, "DATABASES", {})
    database = databases.get(alias) if isinstance(databases, dict) else None
    if not isinstance(database, dict):
        return False

    required_values = (
        database.get("ENGINE"),
        database.get("NAME"),
        database.get("USER"),
        database.get("PASSWORD"),
        database.get("HOST"),
        database.get("PORT"),
    )
    return all(has_required_candidate_value(value) for value in required_values)


def candidate_is_selectable(candidate, membership):
    """Fail closed unless a tenant candidate matches live central authorization."""

    if not isinstance(candidate, dict) or membership is None:
        return False
    if str(candidate.get("id")) != str(getattr(membership, "group_id", "")):
        return False
    if getattr(membership, "status", None) != "active":
        return False

    group = getattr(membership, "group", None)
    if group is None or getattr(group, "status", None) != "active":
        return False
    try:
        config = group.groupdbconfig
    except (ObjectDoesNotExist, AttributeError):
        return False

    required_candidate_values = (
        candidate.get("id"),
        candidate.get("code"),
        candidate.get("name"),
        candidate.get("db_alias"),
    )
    if not all(
        has_required_candidate_value(value)
        for value in required_candidate_values
    ):
        return False

    candidate_alias = str(candidate["db_alias"]).strip()
    central_alias = str(
        getattr(settings, "CENTRAL_DB_ALIAS", "default") or "default"
    ).strip()
    if candidate_alias == central_alias:
        return False

    config_alias = getattr(config, "db_alias", None)
    if not has_required_candidate_value(config_alias):
        return False
    if candidate_alias != str(config_alias).strip():
        return False

    if candidate_alias in configured_static_tenant_aliases():
        return static_tenant_database_config_is_ready(candidate_alias)

    required_config_values = (
        getattr(config, "db_name", None),
        getattr(config, "db_host", None),
        getattr(config, "db_port", None),
        getattr(config, "db_user", None),
        getattr(config, "db_password", None),
    )
    return all(
        has_required_candidate_value(value)
        for value in required_config_values
    )


def selectable_tenant_candidates(user_id, candidates):
    """Filter candidates against current membership/group/database metadata."""

    candidate_ids = [
        str(candidate.get("id"))
        for candidate in candidates
        if isinstance(candidate, dict) and candidate.get("id")
    ]
    if not candidate_ids:
        return []

    central_alias = getattr(settings, "CENTRAL_DB_ALIAS", "default")
    try:
        memberships = (
            UserGroupMap.objects.using(central_alias)
            .select_related("group", "group__groupdbconfig")
            .filter(user_id=user_id, group_id__in=candidate_ids)
        )
        membership_by_group = {
            str(membership.group_id): membership
            for membership in memberships
        }
    except Exception:
        logger.warning("AUTH: tenant candidate eligibility lookup failed")
        return []

    return [
        candidate
        for candidate in candidates
        if candidate_is_selectable(
            candidate,
            membership_by_group.get(str(candidate.get("id"))),
        )
    ]


def refresh_server_issued_tenant_candidates(user_id, issued_candidates):
    """Revalidate only candidates issued into this login session.

    A group can be disabled, a membership revoked, or its DB configuration changed
    while the user is on the selection page. Re-read central metadata before the
    selection is displayed or committed so stale session state cannot be treated
    as current eligibility. Newly granted groups are intentionally not added to an
    existing issued set; they appear on the user's next login.
    """

    issued_ids = {
        str(candidate.get("id"))
        for candidate in (issued_candidates or [])
        if isinstance(candidate, dict) and candidate.get("id")
    }
    if not issued_ids:
        return []

    try:
        current = C.list_tenants_for_user(user_id)
    except Exception:
        logger.warning("AUTH: tenant candidate refresh failed")
        return []

    current_issued = [
        candidate
        for candidate in current
        if isinstance(candidate, dict)
        and str(candidate.get("id")) in issued_ids
    ]
    return selectable_tenant_candidates(user_id, current_issued)
