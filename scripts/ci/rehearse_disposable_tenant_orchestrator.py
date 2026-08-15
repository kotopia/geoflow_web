from __future__ import annotations

from dataclasses import replace
import os
import sys
import uuid


repo = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, repo)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geoflow_project.settings")

import django

django.setup()

from django.test import override_settings  # noqa: E402

from control.services.disposable_full_tenant_backend import (  # noqa: E402
    DisposableFullTenantBackend,
)
from control.services.disposable_postgres_tenant_backend import (  # noqa: E402
    DisposablePostgresConfig,
)
from control.services.tenant_provisioning_backend_readiness import (  # noqa: E402
    inspect_tenant_provisioning_backend_readiness,
)
from control.services.tenant_provisioning_contract import (  # noqa: E402
    TenantProvisioningSnapshot,
    build_tenant_provisioning_plan,
)
from control.services.tenant_provisioning_orchestrator import (  # noqa: E402
    PROVISIONING_CONFIRMATION,
    TenantProvisioningOrchestratorError,
    provision_new_tenant,
)


class _DisposableReadOnlyReadinessProbe:
    """Fake-only positive metadata probe; no provider or central DB calls exist."""

    read_only = True

    def database_target_safe(self, plan):
        return True

    def secret_target_safe(self, plan):
        return True

    def runtime_exact_secret_scope_ready(self, plan):
        return True

    def publication_target_still_available(self, plan):
        return True


def required(name: str) -> str:
    value = str(os.environ.get(name) or "").strip()
    if not value:
        raise RuntimeError(f"missing_{name.lower()}")
    return value


def build_plan(group_id: str):
    snapshot = TenantProvisioningSnapshot(
        group_id=group_id,
        group_code="ci-full-orchestrator",
        group_status="active",
        existing_config_present=False,
        identifier_conflict=False,
    )
    planned = build_tenant_provisioning_plan(
        snapshot,
        db_host=required("CI_PROVISIONER_DB_HOST"),
        db_port=required("CI_PROVISIONER_DB_PORT"),
        provisioning_enabled=True,
        provisioner_ready=True,
        secret_reference_runtime_required=True,
    )
    # Production contract remains execution_available=False. This disposable CI
    # rehearsal opts in only inside this process so the real orchestrator can be
    # exercised without enabling a production-capable backend.
    return replace(planned, execution_available=True)


def build_readiness(plan):
    """Collect the same immutable attestation shape while execution is disabled."""

    disabled_plan = replace(plan, execution_available=False)
    return inspect_tenant_provisioning_backend_readiness(
        disabled_plan,
        _DisposableReadOnlyReadinessProbe(),
    )


def backend_config() -> DisposablePostgresConfig:
    return DisposablePostgresConfig(
        host=required("CI_PROVISIONER_DB_HOST"),
        port=int(required("CI_PROVISIONER_DB_PORT")),
        admin_database=required("CI_PROVISIONER_ADMIN_DATABASE"),
        admin_user=required("CI_PROVISIONER_DB_USER"),
        admin_password=required("CI_PROVISIONER_DB_PASSWORD"),
        sslmode="disable",
    )


def main() -> int:
    plan = build_plan(str(uuid.uuid4()))
    readiness = build_readiness(plan)
    config = backend_config()

    with override_settings(
        ENABLE_TENANT_PROVISIONING=True,
        PROVISIONING_READY=True,
        TENANT_DB_REQUIRE_SECRET_REFERENCES=True,
        TENANT_PROVISIONING_EXECUTOR_MODE=True,
    ):
        # First attempt deliberately returns a non-exact inline IAM policy through
        # the GetRolePolicy-only fake. The production-shaped read-only verifier
        # must reject it before DB-connectivity verification or publication, and
        # the orchestrator must remove only resources owned by this attempt.
        failing_backend = DisposableFullTenantBackend(
            config,
            fail_at="verify_runtime_exact_secret_grant",
        )
        try:
            provision_new_tenant(
                plan,
                failing_backend,
                confirmation=PROVISIONING_CONFIRMATION,
                readiness=readiness,
            )
        except TenantProvisioningOrchestratorError as exc:
            if exc.code != "provisioning_step_failed":
                raise RuntimeError("unexpected_failure_code") from exc
        else:
            raise RuntimeError("simulated_failure_did_not_fail")

        if failing_backend.simulated_iam_read_count != 1:
            raise RuntimeError("failed_attempt_iam_readback_not_exactly_once")
        if not failing_backend.simulated_external_state_clear:
            raise RuntimeError("failed_attempt_external_cleanup_incomplete")

        # Reusing the same deterministic plan proves the failed attempt removed
        # its marker-owned role/database. Any residue causes the second create to
        # fail closed before publication.
        success_backend = DisposableFullTenantBackend(config)
        result = provision_new_tenant(
            plan,
            success_backend,
            confirmation=PROVISIONING_CONFIRMATION,
            readiness=readiness,
        )
        if not result.completed or not result.config_published:
            raise RuntimeError("orchestrator_success_result_invalid")
        if success_backend.simulated_iam_read_count != 1:
            raise RuntimeError("successful_attempt_iam_readback_not_exactly_once")
        if not success_backend.simulated_publication_complete:
            raise RuntimeError("simulated_publication_missing")

        # Successful publication is only in-memory in this CI backend. Explicit
        # fixture teardown is therefore safe and must still use the same marker-
        # guarded provisioning lock for database/role disposal.
        with success_backend.lock(plan):
            success_backend.dispose_successful_rehearsal(plan)

        if not success_backend.simulated_external_state_clear:
            raise RuntimeError("successful_rehearsal_cleanup_incomplete")

    print("tenant_orchestrator_ci_readiness_attestation=required_and_bound")
    print("tenant_orchestrator_ci_failure_rollback=yes")
    print("tenant_orchestrator_ci_retry_after_cleanup=yes")
    print("tenant_orchestrator_ci_post_grant_iam_readback=read_only_exact")
    print("tenant_orchestrator_ci_publish_last_simulated=yes")
    print("tenant_orchestrator_ci_success_cleanup=yes")
    print("tenant_orchestrator_ci_aws_calls=not_performed")
    print("tenant_orchestrator_ci_central_write=not_performed")
    print("tenant_orchestrator_ci_complete=yes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
