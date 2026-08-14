# control/db_router.py
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import connections
from control.middleware import current_db_alias
from control.tenant_migration_context import current_provisioning_migration_alias

import logging
logger = logging.getLogger(__name__)

class TenantRouter:
    CENTRAL_APPS = {"control", "catalog"}
    TENANT_APPS = {"geoflow_ops", "webgisapp"}

    def _resolve_alias(self, model):
        app = model._meta.app_label
        if app in self.CENTRAL_APPS:
            alias = settings.CENTRAL_DB_ALIAS
        elif app in self.TENANT_APPS:
            central_alias = getattr(settings, "CENTRAL_DB_ALIAS", "default")
            alias = current_db_alias() or central_alias
            if alias != central_alias and alias not in connections.settings:
                logger.warning("ROUTER: tenant connection unavailable")
                raise ImproperlyConfigured(
                    "Tenant database connection is unavailable."
                )
        else:
            alias = settings.CENTRAL_DB_ALIAS
        logger.debug(
            "ROUTER: resolved central route"
            if alias == getattr(settings, "CENTRAL_DB_ALIAS", "default")
            else "ROUTER: resolved tenant route"
        )
        return alias

    def db_for_read(self, model, **hints):
        return self._resolve_alias(model)

    def db_for_write(self, model, **hints):
        return self._resolve_alias(model)

    def allow_relation(self, obj1, obj2, **hints):
        return self._resolve_alias(obj1._meta.model) == self._resolve_alias(obj2._meta.model)

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        central_alias = getattr(settings, "CENTRAL_DB_ALIAS", "default")
        if app_label in self.CENTRAL_APPS:
            return db == central_alias
        if app_label in self.TENANT_APPS:
            default_tenant_alias = getattr(
                settings,
                "DEFAULT_TENANT_DB_ALIAS",
                "default",
            )
            if db == default_tenant_alias:
                return True
            provisioning_alias = current_provisioning_migration_alias()
            return bool(provisioning_alias and db == provisioning_alias)
        return db == central_alias
