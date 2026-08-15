import uuid
from dataclasses import replace

from django.test import SimpleTestCase

from control.services.tenant_provisioning_backend_readiness import (
    TenantProvisioningBackendReadinessError,
    inspect_tenant_provisioning_backend_readiness,
)
from control.services.tenant_provisioning_contract import (
    TenantProvisioningSnapshot,
    build_tenant_provisioning_plan,
)


class FakeReadOnlyProbe:
    read_only = True

    def __init__(self, *, outcomes=None, fail_at=None):
        self.outcomes = dict(outcomes or {})
        self.fail_at = fail_at
        self.calls = []

    def _result(self, name):
        self.calls.append(name)
        if self.fail_at == name:
            raise RuntimeError("sensitive provider detail must not escape")
        return self.outcomes.get(name, True)

    def database_target_safe(self, plan):
        return self._result("database_target_safe")

    def secret_target_safe(self, plan):
        return self._result("secret_target_safe")

    def runtime_exact_secret_scope_ready(self, plan):
        return self._result("runtime_exact_secret_scope_ready")

    def publication_target_still_available(self, plan):
        return self._result("publication_target_still_available")


class TenantProvisioningBackendReadinessTests(SimpleTestCase):
    def setUp(self):
        self.group_id = str(uuid.uuid4())
        snapshot = TenantProvisioningSnapshot(
            group_id=self.group_id,
            group_code="readiness-city",
            group_status="active",
            existing_config_present=False,
            identifier_conflict=False,
        )
        self.plan = build_tenant_provisioning_plan(
            snapshot,
            db_host="db.internal.example",
            db_port="5432",
            provisioning_enabled=True,
            provisioner_ready=True,
            secret_reference_runtime_required=True,
        )

    def test_all_read_only_checks_can_pass_without_enabling_execution(self):
        probe = FakeReadOnlyProbe()

        readiness = inspect_tenant_provisioning_backend_readiness(self.plan, probe)

        self.assertTrue(readiness.ready)
        self.assertFalse(readiness.execution_available)
        self.assertFalse(self.plan.execution_available)
        self.assertEqual(
            probe.calls,
            [
                "database_target_safe",
                "secret_target_safe",
                "runtime_exact_secret_scope_ready",
                "publication_target_still_available",
            ],
        )

    def test_non_read_only_probe_is_rejected_before_any_probe_call(self):
        probe = FakeReadOnlyProbe()
        probe.read_only = False

        with self.assertRaises(TenantProvisioningBackendReadinessError) as caught:
            inspect_tenant_provisioning_backend_readiness(self.plan, probe)

        self.assertEqual(caught.exception.code, "read_only_probe_required")
        self.assertEqual(probe.calls, [])

    def test_execution_enabled_plan_is_fail_closed_and_skips_live_reads(self):
        probe = FakeReadOnlyProbe()
        executable_plan = replace(self.plan, execution_available=True)

        readiness = inspect_tenant_provisioning_backend_readiness(executable_plan, probe)

        self.assertFalse(readiness.ready)
        self.assertFalse(readiness.execution_available)
        self.assertEqual(probe.calls, [])
        checks = {check.code: check.ready for check in readiness.checks}
        self.assertFalse(checks["execution_contract_still_disabled"])

    def test_ineligible_plan_skips_live_infrastructure_reads(self):
        probe = FakeReadOnlyProbe()
        disabled_plan = replace(self.plan, provisioning_enabled=False)

        readiness = inspect_tenant_provisioning_backend_readiness(disabled_plan, probe)

        self.assertFalse(readiness.ready)
        self.assertEqual(probe.calls, [])
        checks = {check.code: check.ready for check in readiness.checks}
        self.assertFalse(checks["execution_prerequisites_ready"])

    def test_live_target_conflict_fails_closed(self):
        probe = FakeReadOnlyProbe(
            outcomes={"publication_target_still_available": False}
        )

        readiness = inspect_tenant_provisioning_backend_readiness(self.plan, probe)

        self.assertFalse(readiness.ready)
        checks = {check.code: check.ready for check in readiness.checks}
        self.assertFalse(checks["publication_target_still_available"])
        self.assertFalse(readiness.execution_available)

    def test_probe_exception_becomes_non_secret_failed_check(self):
        probe = FakeReadOnlyProbe(fail_at="secret_target_safe")

        readiness = inspect_tenant_provisioning_backend_readiness(self.plan, probe)

        self.assertFalse(readiness.ready)
        checks = {check.code: check.ready for check in readiness.checks}
        self.assertFalse(checks["secret_target_safe"])
        rendered = repr(readiness)
        self.assertNotIn("sensitive provider detail", rendered)
        self.assertNotIn(self.group_id, rendered)
        self.assertNotIn(self.plan.secret_id, rendered)
        self.assertNotIn(self.plan.db_host, rendered)

    def test_readiness_result_contains_only_codes_and_booleans(self):
        readiness = inspect_tenant_provisioning_backend_readiness(
            self.plan,
            FakeReadOnlyProbe(),
        )

        rendered = repr(readiness)
        self.assertNotIn(self.group_id, rendered)
        self.assertNotIn(self.plan.db_alias, rendered)
        self.assertNotIn(self.plan.db_name, rendered)
        self.assertNotIn(self.plan.db_user, rendered)
        self.assertNotIn(self.plan.db_host, rendered)
        self.assertNotIn(self.plan.secret_id, rendered)
        self.assertNotIn(self.plan.secret_reference, rendered)
