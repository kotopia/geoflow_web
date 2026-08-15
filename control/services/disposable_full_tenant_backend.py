from __future__ import annotations

from typing import Any

from control.services.disposable_postgres_tenant_backend import (
    DisposablePostgresConfig,
    DisposablePostgresTenantBackend,
    DisposableTenantBackendError,
)
from control.services.tenant_provisioning_contract import TenantProvisioningPlan
from control.services.tenant_provisioning_iam_readers import (
    AwsIamInlineTenantSecretGrantReadOnlyVerifier,
)
from control.services.tenant_provisioning_runtime_policy import (
    build_exact_tenant_secret_read_policy,
)


_SIMULATED_RUNTIME_ROLE = "geoflow-ci-runtime-role"
_SIMULATED_RUNTIME_POLICY = "geoflow-ci-tenant-db-secret-read"
_SIMULATED_AWS_REGION = "ap-northeast-2"
_SIMULATED_AWS_ACCOUNT = "123456789012"


class _SimulatedReadOnlyIamClient:
    """In-memory GetRolePolicy-only client used by the disposable rehearsal."""

    def __init__(self, policy_document: dict[str, Any]):
        self._policy_document = policy_document
        self.calls: list[tuple[str, str]] = []

    def get_role_policy(self, *, RoleName: str, PolicyName: str) -> dict[str, Any]:
        self.calls.append((RoleName, PolicyName))
        return {"PolicyDocument": self._policy_document}


class _DisposableLockedReadOnlyReadinessProbe:
    """CI-only JIT probe that performs no mutation and requires the held lock."""

    read_only = True

    def __init__(self, backend: "DisposableFullTenantBackend"):
        self._backend = backend

    def database_target_safe(self, plan: TenantProvisioningPlan) -> bool:
        connection = self._backend._operation_connection()
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM pg_database WHERE datname=%s",
                [plan.db_name],
            )
            database_exists = cursor.fetchone() is not None
            cursor.execute(
                "SELECT 1 FROM pg_roles WHERE rolname=%s",
                [plan.db_user],
            )
            role_exists = cursor.fetchone() is not None
        return not database_exists and not role_exists

    def secret_target_safe(self, plan: TenantProvisioningPlan) -> bool:
        self._backend._operation_connection()
        return self._backend._simulated_secret_id is None

    def runtime_exact_secret_scope_ready(self, plan: TenantProvisioningPlan) -> bool:
        self._backend._operation_connection()
        # The disposable rehearsal has no live IAM identity. This positive result
        # represents only the fake exact-scope boundary already covered by the
        # production-shaped reader tests; no AWS call is possible here.
        return True

    def publication_target_still_available(self, plan: TenantProvisioningPlan) -> bool:
        self._backend._operation_connection()
        return self._backend._simulated_publication is None


class DisposableFullTenantBackend(DisposablePostgresTenantBackend):
    """CI-only full provisioning backend with simulated external dependencies.

    Real Postgres role/database/PostGIS/schema work is delegated to the existing
    localhost-only disposable backend. Secrets Manager, runtime IAM, and central
    GroupDBConfig publication are represented only by in-memory state. No AWS API
    call or central metadata write exists in this class.

    Runtime-IAM verification intentionally reuses the production-shaped read-only
    verifier against a GetRolePolicy-only in-memory client after the simulated
    grant is created. This rehearses the post-grant safety gate without creating
    any production-capable IAM client or mutation path.

    The JIT readiness probe is also read-only and can only be constructed while the
    per-group advisory lock is held. It checks the disposable Postgres catalog with
    SELECT statements and the simulated external/publication state before the first
    provisioning mutation.
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
        self._simulated_runtime_policy: dict[str, Any] | None = None
        self._simulated_iam_read_count = 0
        self._simulated_jit_revalidation_count = 0
        self._simulated_publication: tuple[str, str, str, int, str] | None = None

    def _maybe_fail(self, step: str) -> None:
        if self.fail_at == step:
            raise DisposableTenantBackendError(f"simulated_{step}_failure")

    @staticmethod
    def _secret_resource_pattern(plan: TenantProvisioningPlan) -> str:
        return (
            f"arn:aws:secretsmanager:{_SIMULATED_AWS_REGION}:"
            f"{_SIMULATED_AWS_ACCOUNT}:secret:{plan.secret_id}-??????"
        )

    @property
    def simulated_publication_complete(self) -> bool:
        return self._simulated_publication is not None

    @property
    def simulated_iam_read_count(self) -> int:
        return self._simulated_iam_read_count

    @property
    def simulated_jit_revalidation_count(self) -> int:
        return self._simulated_jit_revalidation_count

    @property
    def simulated_external_state_clear(self) -> bool:
        return (
            self._simulated_secret_id is None
            and not self._simulated_runtime_grant
            and self._simulated_runtime_policy is None
            and self._simulated_publication is None
        )

    def read_only_readiness_probe(self, plan: TenantProvisioningPlan):
        self._operation_connection()
        self._simulated_jit_revalidation_count += 1
        return _DisposableLockedReadOnlyReadinessProbe(self)

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
            if self._simulated_runtime_policy is None:
                raise DisposableTenantBackendError("simulated_runtime_policy_missing")
            return False

        resource_pattern = self._secret_resource_pattern(plan)
        self._simulated_runtime_policy = build_exact_tenant_secret_read_policy(
            secret_resource_pattern=resource_pattern,
        )
        self._simulated_runtime_grant = True
        return True

    def verify_runtime_exact_secret_grant(self, plan: TenantProvisioningPlan) -> None:
        """Rehearse the mandatory post-grant IAM readback safety gate."""

        self._operation_connection()
        if self._simulated_secret_id != plan.secret_id:
            raise DisposableTenantBackendError("simulated_runtime_secret_missing")
        if not self._simulated_runtime_grant or self._simulated_runtime_policy is None:
            raise DisposableTenantBackendError("simulated_runtime_grant_missing")

        policy_document = self._simulated_runtime_policy
        if self.fail_at == "verify_runtime_exact_secret_grant":
            # Deliberately return a non-matching document through the read-only
            # provider surface. This proves the verifier fails closed and the
            # orchestrator compensates before publication.
            policy_document = {"Version": "2012-10-17", "Statement": []}

        client = _SimulatedReadOnlyIamClient(policy_document)
        verifier = AwsIamInlineTenantSecretGrantReadOnlyVerifier(
            client,
            role_name=_SIMULATED_RUNTIME_ROLE,
            policy_name=_SIMULATED_RUNTIME_POLICY,
            secret_id=plan.secret_id,
            secret_resource_pattern=self._secret_resource_pattern(plan),
        )
        ready = verifier.exact_grant_ready()
        self._simulated_iam_read_count += len(client.calls)
        if not ready:
            raise DisposableTenantBackendError("simulated_runtime_grant_not_exact")
        if len(client.calls) != 1:
            raise DisposableTenantBackendError("simulated_runtime_grant_read_count_invalid")

    def verify_runtime_resolution_and_connectivity(
        self,
        plan: TenantProvisioningPlan,
    ) -> None:
        self._operation_connection()
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

    def group_db_config_matches_plan(self, plan: TenantProvisioningPlan) -> bool:
        """Read-only exact publication reconciliation for orchestrator safety."""

        self._operation_connection()
        return self._simulated_publication == (
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
        self._simulated_runtime_policy = None

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
