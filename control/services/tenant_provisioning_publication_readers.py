from __future__ import annotations

from django.db.models import Q

from control.models import GroupDBConfig


class DjangoGroupDBConfigReadOnlyCatalog:
    """Read-only central publication catalog for tenant provisioning readiness.

    The adapter is deliberately limited to ORM existence checks. It performs no
    create/update/delete operation and requires the caller to choose the central
    database alias explicitly so a future production composition cannot silently
    fall back to a tenant connection.
    """

    read_only = True

    def __init__(self, *, using: str, model=GroupDBConfig):
        alias = str(using or "").strip()
        if not alias:
            raise ValueError("central_database_alias_required")
        self._using = alias
        self._model = model

    def _queryset(self):
        return self._model.objects.using(self._using)

    def group_config_exists(self, *, group_id) -> bool:
        return bool(self._queryset().filter(group_id=group_id).exists())

    def identifier_conflict_exists(
        self,
        *,
        group_id,
        db_alias,
        db_name,
        db_user,
    ) -> bool:
        return bool(
            self._queryset()
            .filter(
                Q(db_alias=db_alias)
                | Q(db_name=db_name)
                | Q(db_user=db_user)
            )
            .exclude(group_id=group_id)
            .exists()
        )
