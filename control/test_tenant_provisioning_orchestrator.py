from contextlib import contextmanager
from dataclasses import replace
import uuid

from django.test import SimpleTestCase, override_settings

from control.services.tenant_provisioning_backend_readiness import (
    inspect_tenant_provisioning_backend_readiness,
)
from control.services.tenant_provisioning_contract import (
    TenantProvisioningSnapshot,
    build_tenant_provisioning_plan,
)
from control.services.tenant_provisioning_orchestrator import (
    PROVISIONING_CONFIRMATION,
    TenantProvisioningOrchestratorError,
    provision_new_tenant,
)


class FakeReadOnlyReadinessProbe:
    read_only = True

    def __init__(self, *, backend=None, fail_code=None, raise_code=None):
        self.backend = backend
        self.fail_code = fail_code
        self.raise_code = raise_code

    def _check(self, code):
        if self.backend is not None:
            if not self.backend.lock_held:
                raise RuntimeError("jit_readiness_without_lock")
            self.backend.events.append(f"jit_{code}")
        if self.raise_code == code:
            raise RuntimeError("private_provider_detail")
        return self.fail_code != code

    def database_target_safe(self, plan):
        return self._check("database_target_safe")

    def secret_target_safe(self, plan):
        return self._check("secret_target_safe")

    def runtime_exact_secret_scope_ready(self, plan):
        return self._check("runtime_exact_secret_scope_ready")

    def publication_target_still_available(self, plan):
        return self._check("publication_target_still_available")


def build_test_execution_readiness(plan):
    """Produce a real read-only attestation for an otherwise identical disabled plan."""

    disabled_plan = replace(plan, execution_available=False)
    return inspect_tenant_provisioning_backend_readiness(
        disabled_plan,
        FakeReadOnlyReadinessProbe(),
    )


class FakeProvisioningBackend:
    def __init__(
        self,
        *,
        fail_at=None,
        created=None,
        rollback_fail_at=None,
        reconcile_fail=False,
        jit_fail_code=None,
        jit_raise_code=None,
    ):
        self.events = []
        self.fail_at = fail_at
        self.created = {
            "role": True,
            "database": True,
            "secret": True,
            "runtime_grant": True,
            **(created or {}),
        }
        self.rollback_fail_at = rollback_fail_at
        self.reconcile_fail = reconcile_fail
        self.jit_fail_code = jit_fail_code
        self.jit_raise_code = jit_raise_code
        self.lock_held = False
        self.published = False

    def _step(self, name):
        self.events.append(name)
        if self.fail_at == name:
            raise RuntimeError(name)

    def _rollback(self, name):
        self.events.append(name)
        if not self.lock_held:
            raise RuntimeError("rollback_without_lock")
        if self.rollback_fail_at == name:
            raise RuntimeError(name)

    @contextmanager
    def lock(self, plan):
        self._step("lock_enter")
        self.lock_held = True
        try:
            yield
        finally:
            self.lock_held = False
            self.events.append("lock_exit")

    def read_only_readiness_probe(self, plan):
        if not self.lock_held:
            raise RuntimeError("jit_probe_without_lock")
        self.events.append("jit_probe")
        return FakeReadOnlyReadinessProbe(
            backend=self,
            fail_code=self.jit_fail_code,
            raise_code=self.jit_raise_code,
        )

    def ensure_database_role(self, plan):
        self._step("ensure_database_role")
        return self.created["role"]

    def ensure_database(self, plan):
        self._step("ensure_database")
        return self.created["database"]

    def enable_postgis(self, plan):
        self._step("enable_postgis")

    def apply_tenant_schema(self, plan):
        self._step("apply_tenant_schema")

    def ensure_external_secret(self, plan):
        self._step("ensure_external_secret")
        return self.created["secret"]

    def grant_runtime_exact_secret_read(self, plan):
        self._step("grant_runtime_exact_secret_read")
        return self.created["runtime_grant"]

    def verify_runtime_exact_secret_grant(self, plan):
        self._step("verify_runtime_exact_secret_grant")

    def verify_runtime_resolution_and_connectivity(self, plan):
        self._step("verify_runtime_resolution_and_connectivity")

    def publish_group_db_config(self, plan):
        self.events.append("publish_group_db_config")
        if self.fail_at == "publish_group_db_config":
            raise RuntimeError("publish_group_db_config")
        self.published = True
        if self.fail_at == "publish_group_db_config_after_commit":
            raise RuntimeError("publish_group_db_config_after_commit")

    def group_db_config_matches_plan(self, plan):
        self.events.append("group_db_config_matches_plan")
        if self.reconcile_fail:
            raise RuntimeError("group_db_config_matches_plan")
        return self.published

    def remove_runtime_secret_grant(self, plan):
        self._rollback("rollback_runtime_grant")

    def delete_external_secret(self, plan):
        self._rollback("rollback_secret")

    def drop_database(self, plan):
        self._rollback("rollback_database")

    def drop_database_role(self, plan):
        self._rollback("rollback_role")


@override_settings(
    ENABLE_TENANT_PROVISIONING=True,
    PROVISIONING_READY=True,
    TENANT_DB_REQUIRE_SECRET_REFERENCES=True,
    TENANT_PROVISIONING_EXECUTOR_MODE=True,
)
class TenantProvisioningOrchestratorTests(SimpleTestCase):
    def setUp(self):
        snapshot = TenantProvisioningSnapshot(
            group_id=str(uuid.uuid4()),
            group_code="new-city",
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

    def test_success_publishes_config_last_and_performs_no_rollback(self):
        backend = FakeProvisioningBackend()

        result = provision_new_tenant(
            self.plan,
            backend,
            confirmation=PROVISIONING_CONFIRMATION,
            readiness=self.readiness,
        )

        self.assertTrue(result.completed)
        self.assertTrue(result.config_published)
        self.assertEqual(
            backend.events,
            [
                "lock_enter",
                "jit_probe",
                "jit_database_target_safe",
                "jit_secret_target_safe",
                "jit_runtime_exact_secret_scope_ready",
                "jit_publication_target_still_available",
                "ensure_database_role",
                "ensure_database",
                "enable_postgis",
                "apply_tenant_schema",
                "ensure_external_secret",
                "grant_runtime_exact_secret_read",
                "verify_runtime_exact_secret_grant",
                "verify_runtime_resolution_and_connectivity",
                "publish_group_db_config",
                "lock_exit",
            ],
        )
        self.assertFalse(any(event.startswith("rollback_") for event in backend.events))

    def test_jit_readiness_failure_under_lock_blocks_mutation_without_rollback(self):
        backend = FakeProvisioningBackend(jit_fail_code="database_target_safe")

        with self.assertRaises(TenantProvisioningOrchestratorError) as caught:
            provision_new_tenant(
                self.plan,
                backend,
                confirmation=PROVISIONING_CONFIRMATION,
                readiness=self.readiness,
            )

        self.assertEqual(caught.exception.code, "readiness_revalidation_failed")
        self.assertEqual(
            backend.events,
            [
                "lock_enter",
                "jit_probe",
                "jit_database_target_safe",
                "lock_exit",
            ],
        )
        self.assertNotIn("ensure_database_role", backend.events)
        self.assertNotIn("publish_group_db_config", backend.events)
        self.assertFalse(any(event.startswith("rollback_") for event in backend.events))

    def test_missing_readiness_attestation_blocks_before_backend(self):
        backend = FakeProvisioningBackend()

        with self.assertRaises(TenantProvisioningOrchestratorError) as caught:
            provision_new_tenant(
                self.plan,
                backend,
                confirmation=PROVISIONING_CONFIRMATION,
            )

        self.assertEqual(caught.exception.code, "readiness_attestation_required")
        self.assertEqual(backend.events, [])

    def test_stale_readiness_attestation_blocks_before_backend(self):
        backend = FakeProvisioningBackend()
        changed_target = replace(self.plan, db_host="changed.internal.example")

        with self.assertRaises(TenantProvisioningOrchestratorError) as caught:
            provision_new_tenant(
                changed_target,
                backend,
                confirmation=PROVISIONING_CONFIRMATION,
                readiness=self.readiness,
            )

        self.assertEqual(caught.exception.code, "readiness_attestation_mismatch")
        self.assertEqual(backend.events, [])

    def test_readiness_collected_from_executable_plan_is_rejected(self):
        backend = FakeProvisioningBackend()
        invalid_readiness = inspect_tenant_provisioning_backend_readiness(
            self.plan,
            FakeReadOnlyReadinessProbe(),
        )

        with self.assertRaises(TenantProvisioningOrchestratorError) as caught:
            provision_new_tenant(
                self.plan,
                backend,
                confirmation=PROVISIONING_CONFIRMATION,
                readiness=invalid_readiness,
            )

        self.assertEqual(caught.exception.code, "readiness_attestation_mismatch")
        self.assertEqual(backend.events, [])

    def test_execution_unavailable_blocks_before_backend(self):
        backend = FakeProvisioningBackend()
        blocked_plan = replace(self.plan, execution_available=False)

        with self.assertRaises(TenantProvisioningOrchestratorError) as caught:
            provision_new_tenant(
                blocked_plan,
                backend,
                confirmation=PROVISIONING_CONFIRMATION,
                readiness=self.readiness,
            )

        self.assertEqual(caught.exception.code, "execution_not_available")
        self.assertEqual(backend.events, [])

    def test_confirmation_mismatch_blocks_before_backend(self):
        backend = FakeProvisioningBackend()

        with self.assertRaises(TenantProvisioningOrchestratorError) as caught:
            provision_new_tenant(
                self.plan,
                backend,
                confirmation="wrong",
                readiness=self.readiness,
            )

        self.assertEqual(caught.exception.code, "confirmation_mismatch")
        self.assertEqual(backend.events, [])

    @override_settings(ENABLE_TENANT_PROVISIONING=False)
    def test_live_feature_disable_blocks_stale_executable_plan(self):
        backend = FakeProvisioningBackend()

        with self.assertRaises(TenantProvisioningOrchestratorError) as caught:
            provision_new_tenant(
                self.plan,
                backend,
                confirmation=PROVISIONING_CONFIRMATION,
                readiness=self.readiness,
            )

        self.assertEqual(caught.exception.code, "runtime_feature_disabled")
        self.assertEqual(backend.events, [])

    @override_settings(PROVISIONING_READY=False)
    def test_live_provisioner_not_ready_blocks_stale_plan(self):
        backend = FakeProvisioningBackend()

        with self.assertRaises(TenantProvisioningOrchestratorError) as caught:
            provision_new_tenant(
                self.plan,
                backend,
                confirmation=PROVISIONING_CONFIRMATION,
                readiness=self.readiness,
            )

        self.assertEqual(caught.exception.code, "runtime_provisioner_not_ready")
        self.assertEqual(backend.events, [])

    @override_settings(TENANT_DB_REQUIRE_SECRET_REFERENCES=False)
    def test_live_secret_reference_mode_disable_blocks_execution(self):
        backend = FakeProvisioningBackend()

        with self.assertRaises(TenantProvisioningOrchestratorError) as caught:
            provision_new_tenant(
                self.plan,
                backend,
                confirmation=PROVISIONING_CONFIRMATION,
                readiness=self.readiness,
            )

        self.assertEqual(
            caught.exception.code,
            "runtime_secret_reference_mode_required",
        )
        self.assertEqual(backend.events, [])

    @override_settings(TENANT_PROVISIONING_EXECUTOR_MODE=False)
    def test_public_runtime_without_executor_mode_blocks_before_backend(self):
        backend = FakeProvisioningBackend()

        with self.assertRaises(TenantProvisioningOrchestratorError) as caught:
            provision_new_tenant(
                self.plan,
                backend,
                confirmation=PROVISIONING_CONFIRMATION,
                readiness=self.readiness,
            )

        self.assertEqual(caught.exception.code, "dedicated_executor_mode_required")
        self.assertEqual(backend.events, [])

    def test_schema_failure_rolls_back_inside_lock_scope(self):
        backend = FakeProvisioningBackend(fail_at="apply_tenant_schema")

        with self.assertRaises(TenantProvisioningOrchestratorError) as caught:
            provision_new_tenant(
                self.plan,
                backend,
                confirmation=PROVISIONING_CONFIRMATION,
                readiness=self.readiness,
            )

        self.assertEqual(caught.exception.code, "provisioning_step_failed")
        self.assertEqual(
            backend.events[-3:],
            ["rollback_database", "rollback_role", "lock_exit"],
        )
        self.assertNotIn("rollback_secret", backend.events)
        self.assertNotIn("rollback_runtime_grant", backend.events)

    def test_exact_grant_verification_failure_rolls_back_before_runtime_resolution(self):
        backend = FakeProvisioningBackend(fail_at="verify_runtime_exact_secret_grant")

        with self.assertRaises(TenantProvisioningOrchestratorError) as caught:
            provision_new_tenant(
                self.plan,
                backend,
                confirmation=PROVISIONING_CONFIRMATION,
                readiness=self.readiness,
            )

        self.assertEqual(caught.exception.code, "provisioning_step_failed")
        self.assertNotIn("verify_runtime_resolution_and_connectivity", backend.events)
        self.assertNotIn("publish_group_db_config", backend.events)
        self.assertEqual(
            backend.events[-5:],
            [
                "rollback_runtime_grant",
                "rollback_secret",
                "rollback_database",
                "rollback_role",
                "lock_exit",
            ],
        )

    def test_runtime_verification_failure_rolls_back_in_reverse_external_order(self):
        backend = FakeProvisioningBackend(
            fail_at="verify_runtime_resolution_and_connectivity"
        )

        with self.assertRaises(TenantProvisioningOrchestratorError):
            provision_new_tenant(
                self.plan,
                backend,
                confirmation=PROVISIONING_CONFIRMATION,
                readiness=self.readiness,
            )

        self.assertEqual(
            backend.events[-5:],
            [
                "rollback_runtime_grant",
                "rollback_secret",
                "rollback_database",
                "rollback_role",
                "lock_exit",
            ],
        )
        self.assertNotIn("publish_group_db_config", backend.events)

    def test_publish_failure_reconciles_absence_before_rollback(self):
        backend = FakeProvisioningBackend(fail_at="publish_group_db_config")

        with self.assertRaises(TenantProvisioningOrchestratorError) as caught:
            provision_new_tenant(
                self.plan,
                backend,
                confirmation=PROVISIONING_CONFIRMATION,
                readiness=self.readiness,
            )

        self.assertEqual(caught.exception.code, "provisioning_step_failed")
        self.assertEqual(
            backend.events[-6:],
            [
                "group_db_config_matches_plan",
                "rollback_runtime_grant",
                "rollback_secret",
                "rollback_database",
                "rollback_role",
                "lock_exit",
            ],
        )

    def test_publish_error_after_commit_reconciles_to_success_without_rollback(self):
        backend = FakeProvisioningBackend(
            fail_at="publish_group_db_config_after_commit"
        )

        result = provision_new_tenant(
            self.plan,
            backend,
            confirmation=PROVISIONING_CONFIRMATION,
            readiness=self.readiness,
        )

        self.assertTrue(result.completed)
        self.assertTrue(result.config_published)
        self.assertTrue(backend.published)
        self.assertEqual(
            backend.events[-3:],
            [
                "publish_group_db_config",
                "group_db_config_matches_plan",
                "lock_exit",
            ],
        )
        self.assertFalse(any(event.startswith("rollback_") for event in backend.events))

    def test_unknown_publish_outcome_never_runs_destructive_rollback(self):
        backend = FakeProvisioningBackend(
            fail_at="publish_group_db_config",
            reconcile_fail=True,
        )

        with self.assertRaises(TenantProvisioningOrchestratorError) as caught:
            provision_new_tenant(
                self.plan,
                backend,
                confirmation=PROVISIONING_CONFIRMATION,
                readiness=self.readiness,
            )

        self.assertEqual(caught.exception.code, "publication_outcome_unknown")
        self.assertEqual(
            backend.events[-3:],
            [
                "publish_group_db_config",
                "group_db_config_matches_plan",
                "lock_exit",
            ],
        )
        self.assertFalse(any(event.startswith("rollback_") for event in backend.events))

    def test_reconciled_preexisting_resources_are_never_deleted(self):
        backend = FakeProvisioningBackend(
            fail_at="verify_runtime_resolution_and_connectivity",
            created={
                "role": False,
                "database": False,
                "secret": False,
                "runtime_grant": False,
            },
        )

        with self.assertRaises(TenantProvisioningOrchestratorError):
            provision_new_tenant(
                self.plan,
                backend,
                confirmation=PROVISIONING_CONFIRMATION,
                readiness=self.readiness,
            )

        self.assertFalse(any(event.startswith("rollback_") for event in backend.events))

    def test_partial_created_resources_roll_back_only_owned_subset(self):
        backend = FakeProvisioningBackend(
            fail_at="verify_runtime_resolution_and_connectivity",
            created={
                "role": False,
                "database": True,
                "secret": False,
                "runtime_grant": True,
            },
        )

        with self.assertRaises(TenantProvisioningOrchestratorError):
            provision_new_tenant(
                self.plan,
                backend,
                confirmation=PROVISIONING_CONFIRMATION,
                readiness=self.readiness,
            )

        self.assertIn("rollback_runtime_grant", backend.events)
        self.assertIn("rollback_database", backend.events)
        self.assertNotIn("rollback_secret", backend.events)
        self.assertNotIn("rollback_role", backend.events)
        self.assertLess(
            backend.events.index("rollback_database"),
            backend.events.index("lock_exit"),
        )

    def test_rollback_failure_is_reported_as_incomplete(self):
        backend = FakeProvisioningBackend(
            fail_at="verify_runtime_resolution_and_connectivity",
            rollback_fail_at="rollback_secret",
        )

        with self.assertRaises(TenantProvisioningOrchestratorError) as caught:
            provision_new_tenant(
                self.plan,
                backend,
                confirmation=PROVISIONING_CONFIRMATION,
                readiness=self.readiness,
            )

        self.assertEqual(caught.exception.code, "rollback_incomplete")
        # Best-effort rollback continues after one compensation failure while the
        # lock remains held, then the context exits once cleanup is exhausted.
        self.assertIn("rollback_database", backend.events)
        self.assertIn("rollback_role", backend.events)
        self.assertEqual(backend.events[-1], "lock_exit")
