from dataclasses import replace
import uuid

from django.test import SimpleTestCase

from control.services.tenant_provisioning_backend_readiness import (
    inspect_tenant_provisioning_backend_readiness,
    readiness_allows_execution_candidate,
)
from control.services.tenant_provisioning_contract import (
    TenantProvisioningSnapshot,
    build_tenant_provisioning_plan,
)
from control.services.tenant_provisioning_execution_readiness import (
    TenantProvisioningExecutionReadinessError,
    revalidate_tenant_provisioning_readiness,
)


class RecordingReadOnlyProbe:
    read_only = True

    def __init__(self, *, fail_code=None, raise_code=None):
        self.fail_code = fail_code
        self.raise_code = raise_code
        self.calls = []

    def _check(self, code):
        self.calls.append(code)
        if self.raise_code == code:
            raise RuntimeError("provider_detail_must_not_escape")
        return self.fail_code != code

    def database_target_safe(self, plan):
        return self._check("database_target_safe")

    def secret_target_safe(self, plan):
        return self._check("secret_target_safe")

    def runtime_exact_secret_scope_ready(self, plan):
        return self._check("runtime_exact_secret_scope_ready")

    def publication_target_still_available(self, plan):
        return self._check("publication_target_still_available")


class TenantProvisioningExecutionReadinessTests(SimpleTestCase):
    def setUp(self):
        snapshot = TenantProvisioningSnapshot(
            group_id=str(uuid.uuid4()),
            group_code="jit-readiness-city",
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
        self.disabled_plan = planned
        self.execution_plan = replace(planned, execution_available=True)
        self.initial_readiness = inspect_tenant_provisioning_backend_readiness(
            self.disabled_plan,
            RecordingReadOnlyProbe(),
        )

    def test_refreshes_all_live_checks_for_exact_execution_candidate(self):
        probe = RecordingReadOnlyProbe()

        refreshed = revalidate_tenant_provisioning_readiness(
            self.execution_plan,
            self.initial_readiness,
            probe,
        )

        self.assertEqual(
            probe.calls,
            [
                "database_target_safe",
                "secret_target_safe",
                "runtime_exact_secret_scope_ready",
                "publication_target_still_available",
            ],
        )
        self.assertTrue(refreshed.ready)
        self.assertFalse(refreshed.execution_available)
        self.assertTrue(
            readiness_allows_execution_candidate(refreshed, self.execution_plan)
        )
        self.assertTrue(self.execution_plan.execution_available)

    def test_stale_prior_attestation_blocks_before_any_live_read(self):
        changed_plan = replace(
            self.execution_plan,
            db_host="changed.internal.example",
        )
        probe = RecordingReadOnlyProbe()

        with self.assertRaises(TenantProvisioningExecutionReadinessError) as caught:
            revalidate_tenant_provisioning_readiness(
                changed_plan,
                self.initial_readiness,
                probe,
            )

        self.assertEqual(caught.exception.code, "readiness_attestation_invalid")
        self.assertEqual(probe.calls, [])

    def test_live_target_change_fails_closed(self):
        probe = RecordingReadOnlyProbe(fail_code="database_target_safe")

        with self.assertRaises(TenantProvisioningExecutionReadinessError) as caught:
            revalidate_tenant_provisioning_readiness(
                self.execution_plan,
                self.initial_readiness,
                probe,
            )

        self.assertEqual(caught.exception.code, "readiness_revalidation_failed")
        self.assertIn("database_target_safe", probe.calls)

    def test_probe_exception_is_reduced_to_non_secret_failure(self):
        probe = RecordingReadOnlyProbe(raise_code="secret_target_safe")

        with self.assertRaises(TenantProvisioningExecutionReadinessError) as caught:
            revalidate_tenant_provisioning_readiness(
                self.execution_plan,
                self.initial_readiness,
                probe,
            )

        self.assertEqual(caught.exception.code, "readiness_revalidation_failed")
        self.assertNotIn("provider_detail_must_not_escape", str(caught.exception))

    def test_non_read_only_probe_is_rejected(self):
        probe = RecordingReadOnlyProbe()
        probe.read_only = False

        with self.assertRaises(TenantProvisioningExecutionReadinessError) as caught:
            revalidate_tenant_provisioning_readiness(
                self.execution_plan,
                self.initial_readiness,
                probe,
            )

        self.assertEqual(caught.exception.code, "readiness_revalidation_failed")
        self.assertEqual(probe.calls, [])

    def test_revalidation_never_enables_a_disabled_plan(self):
        probe = RecordingReadOnlyProbe()

        with self.assertRaises(TenantProvisioningExecutionReadinessError) as caught:
            revalidate_tenant_provisioning_readiness(
                self.disabled_plan,
                self.initial_readiness,
                probe,
            )

        self.assertEqual(caught.exception.code, "readiness_attestation_invalid")
        self.assertEqual(probe.calls, [])
        self.assertFalse(self.disabled_plan.execution_available)
