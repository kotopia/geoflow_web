import uuid
from dataclasses import replace

from django.test import SimpleTestCase

from control.services.tenant_provisioning_backend_readiness import (
    TenantProvisioningBackendReadinessError,
    inspect_tenant_provisioning_backend_readiness,
    readiness_matches_plan,
)
from control.services.tenant_provisioning_contract import (
    TenantProvisioningSnapshot,
    build_tenant_provisioning_plan,
)
from control.services.tenant_provisioning_production_probe import (
    ProductionShapeReadOnlyTenantProvisioningProbe,
)


class FakeDatabaseCatalog:
    read_only = True

    def __init__(self, ledger, *, database_exists=False, role_exists=False, fail_at=None):
        self.ledger = ledger
        self.database_present = database_exists
        self.role_present = role_exists
        self.fail_at = fail_at

    def _record(self, name):
        self.ledger.append(name)
        if self.fail_at == name:
            raise RuntimeError("provider detail must remain private")

    def database_exists(self, *, host, port, database):
        self._record("database_exists")
        return self.database_present

    def role_exists(self, *, host, port, role):
        self._record("role_exists")
        return self.role_present


class FakeSecretCatalog:
    read_only = True

    def __init__(self, ledger, *, exists=False, fail=False):
        self.ledger = ledger
        self.exists = exists
        self.fail = fail

    def secret_exists(self, *, secret_id):
        self.ledger.append("secret_exists")
        if self.fail:
            raise RuntimeError("secret provider detail must remain private")
        return self.exists


class FakeRuntimeSecretScope:
    read_only = True

    def __init__(self, ledger, *, exact_ready=True):
        self.ledger = ledger
        self.exact_ready = exact_ready

    def exact_secret_read_ready(self, *, secret_id):
        self.ledger.append("exact_secret_read_ready")
        return self.exact_ready


class FakePublicationCatalog:
    read_only = True

    def __init__(self, ledger, *, existing=False, conflict=False):
        self.ledger = ledger
        self.existing = existing
        self.conflict = conflict

    def group_config_exists(self, *, group_id):
        self.ledger.append("group_config_exists")
        return self.existing

    def identifier_conflict_exists(
        self,
        *,
        group_id,
        db_alias,
        db_name,
        db_user,
    ):
        self.ledger.append("identifier_conflict_exists")
        return self.conflict


class ProductionShapeReadOnlyTenantProvisioningProbeTests(SimpleTestCase):
    def setUp(self):
        self.group_id = str(uuid.uuid4())
        snapshot = TenantProvisioningSnapshot(
            group_id=self.group_id,
            group_code="production-shape-city",
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

    def _probe(
        self,
        *,
        database_exists=False,
        role_exists=False,
        secret_exists=False,
        exact_scope_ready=True,
        publication_exists=False,
        publication_conflict=False,
        secret_fail=False,
    ):
        ledger = []
        probe = ProductionShapeReadOnlyTenantProvisioningProbe(
            database_catalog=FakeDatabaseCatalog(
                ledger,
                database_exists=database_exists,
                role_exists=role_exists,
            ),
            secret_catalog=FakeSecretCatalog(
                ledger,
                exists=secret_exists,
                fail=secret_fail,
            ),
            runtime_secret_scope=FakeRuntimeSecretScope(
                ledger,
                exact_ready=exact_scope_ready,
            ),
            publication_catalog=FakePublicationCatalog(
                ledger,
                existing=publication_exists,
                conflict=publication_conflict,
            ),
        )
        return probe, ledger

    def test_all_clear_production_shape_is_ready_but_never_executable(self):
        probe, ledger = self._probe()

        readiness = inspect_tenant_provisioning_backend_readiness(self.plan, probe)

        self.assertTrue(readiness.ready)
        self.assertFalse(readiness.execution_available)
        self.assertFalse(self.plan.execution_available)
        self.assertTrue(readiness_matches_plan(readiness, self.plan))
        self.assertEqual(
            ledger,
            [
                "database_exists",
                "role_exists",
                "secret_exists",
                "exact_secret_read_ready",
                "group_config_exists",
                "identifier_conflict_exists",
            ],
        )

    def test_database_or_role_collision_fails_closed(self):
        for collision in ("database", "role"):
            with self.subTest(collision=collision):
                probe, _ = self._probe(
                    database_exists=collision == "database",
                    role_exists=collision == "role",
                )
                readiness = inspect_tenant_provisioning_backend_readiness(
                    self.plan,
                    probe,
                )
                checks = {check.code: check.ready for check in readiness.checks}
                self.assertFalse(readiness.ready)
                self.assertFalse(checks["database_target_safe"])

    def test_secret_collision_or_non_exact_runtime_scope_fails_closed(self):
        cases = (
            {"secret_exists": True},
            {"exact_scope_ready": False},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                probe, _ = self._probe(**overrides)
                readiness = inspect_tenant_provisioning_backend_readiness(
                    self.plan,
                    probe,
                )
                self.assertFalse(readiness.ready)
                self.assertFalse(readiness.execution_available)

    def test_existing_or_conflicting_publication_target_fails_closed(self):
        cases = (
            {"publication_exists": True},
            {"publication_conflict": True},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                probe, _ = self._probe(**overrides)
                readiness = inspect_tenant_provisioning_backend_readiness(
                    self.plan,
                    probe,
                )
                checks = {check.code: check.ready for check in readiness.checks}
                self.assertFalse(readiness.ready)
                self.assertFalse(checks["publication_target_still_available"])

    def test_ambiguous_provider_failure_is_reduced_to_failed_boolean_check(self):
        probe, _ = self._probe(secret_fail=True)

        readiness = inspect_tenant_provisioning_backend_readiness(self.plan, probe)

        checks = {check.code: check.ready for check in readiness.checks}
        self.assertFalse(readiness.ready)
        self.assertFalse(checks["secret_target_safe"])
        rendered = repr(readiness)
        self.assertNotIn("secret provider detail", rendered)
        self.assertNotIn(self.group_id, rendered)
        self.assertNotIn(self.plan.secret_id, rendered)
        self.assertNotIn(self.plan.db_host, rendered)

    def test_any_non_read_only_dependency_rejects_probe_before_reads(self):
        probe, ledger = self._probe()
        probe.secret_catalog.read_only = False

        with self.assertRaises(TenantProvisioningBackendReadinessError) as caught:
            inspect_tenant_provisioning_backend_readiness(self.plan, probe)

        self.assertEqual(caught.exception.code, "read_only_probe_required")
        self.assertEqual(ledger, [])

    def test_readiness_from_adapter_cannot_be_reused_after_plan_change(self):
        probe, _ = self._probe()
        readiness = inspect_tenant_provisioning_backend_readiness(self.plan, probe)
        changed_plan = replace(self.plan, db_name=self.plan.db_name + "_other")

        self.assertTrue(readiness_matches_plan(readiness, self.plan))
        self.assertFalse(readiness_matches_plan(readiness, changed_plan))
