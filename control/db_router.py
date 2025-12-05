# control/db_router.py
from django.conf import settings
from control.middleware import current_db_alias

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
            alias = current_db_alias() or getattr(settings, "CENTRAL_DB_ALIAS", "default")
        else:
            alias = settings.CENTRAL_DB_ALIAS
        logger.debug("ROUTER: app=%s -> alias=%s", app, alias)
        return alias

    def db_for_read(self, model, **hints):
        return self._resolve_alias(model)

    def db_for_write(self, model, **hints):
        return self._resolve_alias(model)

    def allow_relation(self, obj1, obj2, **hints):
        return self._resolve_alias(obj1._meta.model) == self._resolve_alias(obj2._meta.model)

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label in self.CENTRAL_APPS:
            return db == settings.CENTRAL_DB_ALIAS
        if app_label in self.TENANT_APPS:
            return db == getattr(settings, "DEFAULT_TENANT_DB_ALIAS", "default")
        return db == settings.CENTRAL_DB_ALIAS
