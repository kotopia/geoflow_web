from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from control.services.tenant_provisioning_contract import TenantProvisioningPlan


class ReadOnlyDatabaseCatalog(Protocol):
    """Read-only database metadata boundary.

    ``False`` from an existence method must mean a definitive not-found result.
    Permission, transport, authentication, or ambiguous provider failures must be
    raised so the outer readiness contract fails closed.
    """

    read_only: bool

    def database_exists(self, *, host: str, port: int, database: str) -> bool: ...

    def role_exists(self, *, host: str, port: int, role: str) -> bool: ...


class ReadOnlySecretCatalog(Protocol):
    """Read-only secret metadata boundary; it must never return secret values."""

    read_only: bool

    def secret_exists(self, *, secret_id: str) -> bool: ...


class ReadOnlyRuntimeSecretScope(Protocol):
    """Read-only runtime-policy boundary for the exact planned secret only."""

    read_only: bool

    def exact_secret_read_ready(self, *, secret_id: str) -> bool: ...


class ReadOnlyPublicationCatalog(Protocol):
    """Read-only central metadata boundary for final GroupDBConfig publication."""

    read_only: bool

    def group_config_exists(self, *, group_id: str) -> bool: ...

    def identifier_conflict_exists(
        self,
        *,
        group_id: str,
        db_alias: str,
        db_name: str,
        db_user: str,
    ) -> bool: ...


@dataclass(frozen=True)
class ProductionShapeReadOnlyTenantProvisioningProbe:
    """Production-shaped probe assembled only from read-only dependencies.

    This adapter intentionally contains no provider constructors, credentials,
    mutation methods, ORM writes, or execution switch. Future provider-specific
    readers can be injected behind these narrow interfaces after their own
    read-only behavior is proven. Until then, CI can exercise the same shape with
    fakes without touching AWS, production PostgreSQL, IAM, or central metadata.
    """

    database_catalog: ReadOnlyDatabaseCatalog
    secret_catalog: ReadOnlySecretCatalog
    runtime_secret_scope: ReadOnlyRuntimeSecretScope
    publication_catalog: ReadOnlyPublicationCatalog

    @property
    def read_only(self) -> bool:
        return all(
            bool(getattr(dependency, "read_only", False)) is True
            for dependency in (
                self.database_catalog,
                self.secret_catalog,
                self.runtime_secret_scope,
                self.publication_catalog,
            )
        )

    def _require_read_only_dependencies(self) -> None:
        if not self.read_only:
            raise RuntimeError("read_only_dependency_required")

    def database_target_safe(self, plan: TenantProvisioningPlan) -> bool:
        self._require_read_only_dependencies()
        database_exists = bool(
            self.database_catalog.database_exists(
                host=plan.db_host,
                port=plan.db_port,
                database=plan.db_name,
            )
        )
        role_exists = bool(
            self.database_catalog.role_exists(
                host=plan.db_host,
                port=plan.db_port,
                role=plan.db_user,
            )
        )
        return not database_exists and not role_exists

    def secret_target_safe(self, plan: TenantProvisioningPlan) -> bool:
        self._require_read_only_dependencies()
        return not bool(self.secret_catalog.secret_exists(secret_id=plan.secret_id))

    def runtime_exact_secret_scope_ready(self, plan: TenantProvisioningPlan) -> bool:
        self._require_read_only_dependencies()
        return bool(
            self.runtime_secret_scope.exact_secret_read_ready(secret_id=plan.secret_id)
        )

    def publication_target_still_available(self, plan: TenantProvisioningPlan) -> bool:
        self._require_read_only_dependencies()
        existing_config = bool(
            self.publication_catalog.group_config_exists(group_id=plan.group_id)
        )
        identifier_conflict = bool(
            self.publication_catalog.identifier_conflict_exists(
                group_id=plan.group_id,
                db_alias=plan.db_alias,
                db_name=plan.db_name,
                db_user=plan.db_user,
            )
        )
        return not existing_config and not identifier_conflict
