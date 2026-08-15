from __future__ import annotations

from control.services.disposable_postgres_tenant_backend import (
    DisposablePostgresConfig,
    DisposablePostgresTenantBackend,
    DisposableTenantBackendError,
)
from control.services.tenant_provisioning_contract import TenantProvisioningPlan


class DisposableFullTenantBackend(DisposablePostgresTenantBackend):
    """CI-only full provisioning backend with simulated external dependencies.

    Real Postgres role/database/PostGIS/schema work is delegated to the existing
    localhost-only disposable backend. Secrets Manager, runtime IAM, and central
    GroupDBConfig publication are represented only by in-memory state. No AWS API
    call or central metadata write exists in this class.
    """

    def __init__(
        self,
        config: DisposablePostgresConfig,
        *,
        fail_at: str | None = None,
    ):
        super().__init__(config)
        self.fail_at = str(fail_at or "").strip() or None
        self._simulated_secret_id: str | None = None
        self._simulated_runtime_grant = False
        self._simulated_publication: tuple[str, str, str, int, str] | None = None

    def _maybe_fail(self, step: str) -> None:
        if self.fail_at == step:
            raise DisposableTenantBackendError(f"simulated_{step}_failure")

    @property
    def simulated_publication_complete(self) -> bool:
        return self._simulated_publication is not None

    @property
    def simulated_external_state_clear(self) -> bool:
        return (
            self._simulated_secret_id is None
            and not self._simulated_runtime_grant
            and self._simulated_publication is None
        )

    def ensure_external_secret(self, plan: TenantProvisioningPlan) -> bool:
        self._operation_connection()
        self._maybe_fail("ensure_external_secret")
        if self._simulated_secret_id is not None:
            if self._simulated_secret_id == plan.secret_id:
                return False
            raise DisposableTenantBackendError("simulated_secret_name_conflict")
        self._simulated_secret_id = plan.secret_id
        return True

    def grant_runtime_exact_secret_read(self, plan: TenantProvisioningPlan) -> bool:
        self._operation_connection()
        self._maybe_fail("grant_runtime_exact_secret_read")
        if self._simulated_secret_id != plan.secret_id:
            raise DisposableTenantBackendError("simulated_secret_required_before_grant")
        if self._simulated_runtime_grant:
            return False
        self._simulated_runtime_grant = True
        return True

    def verify_runtime_resolution_and_connectivity(
        self,
        plan: TenantProvisioningPlan,
    ) -> None:
        self._operation_connection()
        if self._simulated_secret_id != plan.secret_id:
            raise DisposableTenantBackendError("simulated_runtime_secret_missing")
        if not self._simulated_runtime_grant:
            raise DisposableTenantBackendError("simulated_runtime_grant_missing")
        self.verify_database_schema(plan)
        self._maybe_fail("verify_runtime_resolution_and_connectivity")

    def publish_group_db_config(self, plan: TenantProvisioningPlan) -> None:
        self._operation_connection()
        self._maybe_fail("publish_group_db_config")
        if self._simulated_secret_id != plan.secret_id:
            raise DisposableTenantBackendError("simulated_publish_secret_missing")
        if not self._simulated_runtime_grant:
            raise DisposableTenantBackendError("simulated_publish_grant_missing")
        if self._simulated_publication is not None:
            raise DisposableTenantBackendError("simulated_config_already_published")
        self._simulated_publication = (
            plan.db_alias,
            plan.db_name,
            plan.db_host,
            int(plan.db_port),
            plan.secret_reference,
        )

    def remove_runtime_secret_grant(self, plan: TenantProvisioningPlan) -> None:
        self._operation_connection()
        if not self._simulated_runtime_grant:
            raise DisposableTenantBackendError("simulated_runtime_grant_missing")
        self._simulated_runtime_grant = False

    def delete_external_secret(self, plan: TenantProvisioningPlan) -> None:
        self._operation_connection()
        if self._simulated_secret_id != plan.secret_id:
            raise DisposableTenantBackendError("simulated_secret_ownership_mismatch")
        if self._simulated_runtime_grant:
            raise DisposableTenantBackendError("simulated_grant_must_be_removed_first")
        self._simulated_secret_id = None

    def dispose_successful_rehearsal(self, plan: TenantProvisioningPlan) -> None:
        """Delete only this CI backend's successfully rehearsed resources.

        This is test-fixture teardown, not production rollback. It requires the
        same provisioning lock and first clears the in-memory publication marker,
        then reverses the simulated external state before marker-guarded DB cleanup.
        """

        self._operation_connection()
        if self._simulated_publication is None:
            raise DisposableTenantBackendError("simulated_publication_required")
        self._simulated_publication = None
        if self._simulated_runtime_grant:
            self.remove_runtime_secret_grant(plan)
        if self._simulated_secret_id is not None:
            self.delete_external_secret(plan)
        self.drop_database(plan)
        self.drop_database_role(plan)
