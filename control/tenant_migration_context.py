from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


_provisioning_migration_alias: ContextVar[str | None] = ContextVar(
    "geoflow_provisioning_migration_alias",
    default=None,
)


def current_provisioning_migration_alias() -> str | None:
    """Return the explicitly authorized dynamic migration alias for this context."""

    value = _provisioning_migration_alias.get()
    return str(value).strip() if value else None


def _validate_dynamic_alias(alias: object) -> str:
    value = str(alias or "").strip()
    central_alias = str(
        getattr(settings, "CENTRAL_DB_ALIAS", "default") or "default"
    ).strip()
    if not value:
        raise ImproperlyConfigured("Tenant provisioning migration alias is required")
    if value == central_alias:
        raise ImproperlyConfigured(
            "Central database cannot be used as a tenant provisioning migration alias"
        )
    return value


@contextmanager
def allow_tenant_provisioning_migrations(alias: object):
    """Authorize tenant-app migrations for exactly one dynamic alias in this context.

    The normal router contract remains unchanged outside this context. ContextVar
    scoping prevents one request/task/thread from globally opening migrations for
    another alias. This helper only changes router authorization; it does not
    register a database connection and never runs migrations itself.
    """

    validated = _validate_dynamic_alias(alias)
    token = _provisioning_migration_alias.set(validated)
    try:
        yield validated
    finally:
        _provisioning_migration_alias.reset(token)
