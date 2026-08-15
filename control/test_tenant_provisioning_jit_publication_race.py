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
class TenantProvisioningJitPublicationRaceTests(SimpleTestCase):
    def setUp(self):
        snapshot = TenantProvisioningSnapshot(
            group_id=str(uuid.uuid4()),
            group_code="race-city",
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

    def test_new_publication_conflict_after_initial_attestation_blocks_first_mutation(self):
        # Initial read-only readiness is clean. The fake backend then represents a
        # central publication target claimed by another actor before lock-scoped JIT
        # revalidation. The orchestrator must detect that race before any mutation.
        readiness = build_test_execution_readiness(self.plan)
        self.assertTrue(readiness.ready)

        backend = FakeProvisioningBackend(
            jit_fail_code="publication_target_still_available"
        )

        with self.assertRaises(TenantProvisioningOrchestratorError) as caught:
            provision_new_tenant(
                self.plan,
                backend,
                confirmation=PROVISIONING_CONFIRMATION,
                readiness=readiness,
            )

        self.assertEqual(caught.exception.code, "readiness_revalidation_failed")
        self.assertEqual(
            backend.events,
            [
                "lock_enter",
                "jit_probe",
                "jit_database_target_safe",
                "jit_secret_target_safe",
                "jit_runtime_exact_secret_scope_ready",
                "jit_publication_target_still_available",
                "lock_exit",
            ],
        )

        mutation_events = {
            "ensure_database_role",
            "ensure_database",
            "enable_postgis",
            "apply_tenant_schema",
            "ensure_external_secret",
            "grant_runtime_exact_secret_read",
            "verify_runtime_exact_secret_grant",
            "verify_runtime_resolution_and_connectivity",
            "publish_group_db_config",
        }
        self.assertTrue(mutation_events.isdisjoint(backend.events))
        self.assertFalse(any(event.startswith("rollback_") for event in backend.events))
        self.assertFalse(backend.published)
