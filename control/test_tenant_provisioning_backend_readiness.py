import uuid
from dataclasses import replace

from django.test import SimpleTestCase

from control.services.tenant_provisioning_backend_readiness import (
    TenantProvisioningBackendReadiness,
    TenantProvisioningBackendReadinessCheck,
    TenantProvisioningBackendReadinessError,
    inspect_tenant_provisioning_backend_readiness,
    readiness_allows_execution_candidate,
    readiness_matches_plan,
    tenant_provisioning_execution_target_binding,
    tenant_provisioning_plan_binding,
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
        self.assertTrue(readiness_matches_plan(readiness, self.plan))
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
        self.assertTrue(readiness_matches_plan(readiness, executable_plan))
        self.assertEqual(probe.calls, [])
        checks = {check.code: check.ready for check in readiness.checks}
        self.assertFalse(checks["execution_contract_still_disabled"])

    def test_ineligible_plan_skips_live_infrastructure_reads(self):
        probe = FakeReadOnlyProbe()
        disabled_plan = replace(self.plan, provisioning_enabled=False)

        readiness = inspect_tenant_provisioning_backend_readiness(disabled_plan, probe)

        self.assertFalse(readiness.ready)
        self.assertTrue(readiness_matches_plan(readiness, disabled_plan))
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

    def test_plan_binding_is_stable_and_covers_execution_relevant_fields(self):
        first = tenant_provisioning_plan_binding(self.plan)
        second = tenant_provisioning_plan_binding(self.plan)

        self.assertEqual(first, second)
        self.assertRegex(first, r"^sha256:[0-9a-f]{64}$")
        self.assertNotEqual(
            first,
            tenant_provisioning_plan_binding(
                replace(self.plan, db_host="different.internal.example")
            ),
        )
        self.assertNotEqual(
            first,
            tenant_provisioning_plan_binding(
                replace(self.plan, execution_available=True)
            ),
        )
        self.assertNotEqual(
            first,
            tenant_provisioning_plan_binding(
                replace(self.plan, secret_reference=self.plan.secret_reference + "-other")
            ),
        )

    def test_execution_target_binding_excludes_only_execution_switch(self):
        disabled = tenant_provisioning_execution_target_binding(self.plan)
        executable = tenant_provisioning_execution_target_binding(
            replace(self.plan, execution_available=True)
        )

        self.assertEqual(disabled, executable)
        self.assertRegex(disabled, r"^sha256:[0-9a-f]{64}$")

        changes = (
            {"group_id": str(uuid.uuid4())},
            {"group_code": self.plan.group_code + "-other"},
            {"db_alias": self.plan.db_alias + "_other"},
            {"db_name": self.plan.db_name + "_other"},
            {"db_user": self.plan.db_user + "_other"},
            {"db_host": "different.internal.example"},
            {"db_port": self.plan.db_port + 1},
            {"secret_id": self.plan.secret_id + "-other"},
            {"secret_reference": self.plan.secret_reference + "-other"},
            {"provisioning_enabled": False},
            {"provisioner_ready": False},
            {"secret_reference_runtime_required": False},
            {"runtime_secret_grant_required": False},
        )
        for change in changes:
            with self.subTest(change=change):
                changed = replace(self.plan, **change)
                self.assertNotEqual(
                    disabled,
                    tenant_provisioning_execution_target_binding(changed),
                )

    def test_passing_disabled_readiness_can_attest_only_matching_execution_candidate(self):
        readiness = inspect_tenant_provisioning_backend_readiness(
            self.plan,
            FakeReadOnlyProbe(),
        )
        executable_plan = replace(self.plan, execution_available=True)

        self.assertTrue(readiness.ready)
        self.assertTrue(
            readiness_allows_execution_candidate(readiness, executable_plan)
        )
        self.assertFalse(readiness_allows_execution_candidate(readiness, self.plan))
        self.assertFalse(
            readiness_allows_execution_candidate(
                readiness,
                replace(executable_plan, db_port=executable_plan.db_port + 1),
            )
        )
        self.assertFalse(
            readiness_allows_execution_candidate(
                readiness,
                replace(executable_plan, secret_id=executable_plan.secret_id + "-other"),
            )
        )

    def test_failed_readiness_never_attests_execution_candidate(self):
        readiness = inspect_tenant_provisioning_backend_readiness(
            self.plan,
            FakeReadOnlyProbe(outcomes={"database_target_safe": False}),
        )
        executable_plan = replace(self.plan, execution_available=True)

        self.assertFalse(readiness.ready)
        self.assertFalse(
            readiness_allows_execution_candidate(readiness, executable_plan)
        )

    def test_incomplete_or_duplicate_attestation_never_allows_candidate(self):
        executable_plan = replace(self.plan, execution_available=True)
        binding = tenant_provisioning_execution_target_binding(self.plan)

        incomplete = TenantProvisioningBackendReadiness(
            checks=(
                TenantProvisioningBackendReadinessCheck(
                    code="database_target_safe",
                    ready=True,
                ),
            ),
            plan_binding="sha256:" + "0" * 64,
            execution_target_binding=binding,
        )
        self.assertTrue(incomplete.ready)
        self.assertFalse(
            readiness_allows_execution_candidate(incomplete, executable_plan)
        )

        complete = inspect_tenant_provisioning_backend_readiness(
            self.plan,
            FakeReadOnlyProbe(),
        )
        duplicated = TenantProvisioningBackendReadiness(
            checks=complete.checks + (complete.checks[0],),
            plan_binding=complete.plan_binding,
            execution_target_binding=complete.execution_target_binding,
        )
        self.assertTrue(duplicated.ready)
        self.assertFalse(
            readiness_allows_execution_candidate(duplicated, executable_plan)
        )

    def test_readiness_cannot_be_reused_for_modified_plan(self):
        readiness = inspect_tenant_provisioning_backend_readiness(
            self.plan,
            FakeReadOnlyProbe(),
        )
        changed_plan = replace(self.plan, db_port=self.plan.db_port + 1)

        self.assertTrue(readiness_matches_plan(readiness, self.plan))
        self.assertFalse(readiness_matches_plan(readiness, changed_plan))

    def test_readiness_result_exposes_only_codes_booleans_and_digests(self):
        readiness = inspect_tenant_provisioning_backend_readiness(
            self.plan,
            FakeReadOnlyProbe(),
        )

        self.assertRegex(readiness.plan_binding, r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(
            readiness.execution_target_binding,
            r"^sha256:[0-9a-f]{64}$",
        )
        rendered = repr(readiness)
        self.assertNotIn(self.group_id, rendered)
        self.assertNotIn(self.plan.db_alias, rendered)
        self.assertNotIn(self.plan.db_name, rendered)
        self.assertNotIn(self.plan.db_user, rendered)
        self.assertNotIn(self.plan.db_host, rendered)
        self.assertNotIn(self.plan.secret_id, rendered)
        self.assertNotIn(self.plan.secret_reference, rendered)
