from dataclasses import replace
import uuid

from django.test import SimpleTestCase, override_settings

from control.services.tenant_provisioning_contract import (
    TenantProvisioningSnapshot,
    build_tenant_provisioning_plan,
)
from control.services.tenant_provisioning_orchestrator import (
    PROVISIONING_CONFIRMATION,
    TenantProvisioningOrchestratorError,
    provision_new_tenant,
)
from control.test_tenant_provisioning_orchestrator import (
    FakeProvisioningBackend,
    build_test_execution_readiness,
)


@override_settings(
    ENABLE_TENANT_PROVISIONING=True,
    PROVISIONING_READY=True,
    TENANT_DB_REQUIRE_SECRET_REFERENCES=True,
    TENANT_PROVISIONING_EXECUTOR_MODE=True,
)
class PreexistingRuntimeGrantRollbackTests(SimpleTestCase):
    """Lock retry compensation to resources owned by the current attempt."""

    def setUp(self):
        snapshot = TenantProvisioningSnapshot(
            group_id=str(uuid.uuid4()),
            group_code="preexisting-grant-city",
            group_status="active",
            existing_config_present=False,
            identifier_conflict=False,
        )
        planned = build_tenant_provisioning_plan(
            snapshot,
            db_host="db.internal.example",
            db_port="5432",
            provisioning_enabled=True,
            provisioner_ready=True,
            secret_reference_runtime_required=True,
        )
        self.plan = replace(planned, execution_available=True)
        self.readiness = build_test_execution_readiness(self.plan)

    def test_failed_exact_readback_never_removes_preexisting_runtime_grant(self):
        # A retry may reconcile an already-correct IAM grant instead of creating
        # it. The backend therefore reports runtime_grant_created=False. Even if
        # the mandatory post-grant readback then fails, compensation must not
        # delete that pre-existing grant; only resources created by this attempt
        # may be reversed.
        backend = FakeProvisioningBackend(
            fail_at="verify_runtime_exact_secret_grant",
            created={
                "role": True,
                "database": True,
                "secret": True,
                "runtime_grant": False,
            },
        )

        with self.assertRaises(TenantProvisioningOrchestratorError) as caught:
            provision_new_tenant(
                self.plan,
                backend,
                confirmation=PROVISIONING_CONFIRMATION,
                readiness=self.readiness,
            )

        self.assertEqual(caught.exception.code, "provisioning_step_failed")
        self.assertIn("verify_runtime_exact_secret_grant", backend.events)
        self.assertNotIn("verify_runtime_resolution_and_connectivity", backend.events)
        self.assertNotIn("publish_group_db_config", backend.events)
        self.assertNotIn("rollback_runtime_grant", backend.events)
        self.assertEqual(
            backend.events[-4:],
            [
                "rollback_secret",
                "rollback_database",
                "rollback_role",
                "lock_exit",
            ],
        )
