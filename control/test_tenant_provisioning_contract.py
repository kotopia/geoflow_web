import uuid
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from control.services.tenant_db_secret_resolver import SECRET_REFERENCE_PREFIX
from control.services.tenant_provisioning_contract import (
    PROVISIONING_EXECUTION_SEQUENCE,
    PROVISIONING_ROLLBACK_SEQUENCE,
    TenantProvisioningContractError,
    TenantProvisioningSnapshot,
    build_tenant_provisioning_plan,
    build_tenant_secret_reference,
    derive_tenant_identifiers,
    inspect_tenant_provisioning_plan,
)


class TenantProvisioningContractTests(SimpleTestCase):
    def setUp(self):
        self.group_id = str(uuid.uuid4())
        self.snapshot = TenantProvisioningSnapshot(
            group_id=self.group_id,
            group_code="new-city",
            group_status="active",
            existing_config_present=False,
            identifier_conflict=False,
        )

    def _plan(self, **overrides):
        params = {
            "db_host": "db.internal.example",
            "db_port": "5432",
            "provisioning_enabled": False,
            "provisioner_ready": True,
            "secret_reference_runtime_required": True,
        }
        params.update(overrides)
        return build_tenant_provisioning_plan(self.snapshot, **params)

    def test_identifiers_are_deterministic_safe_and_uuid_scoped(self):
        first = derive_tenant_identifiers(self.group_id, "New City")
        second = derive_tenant_identifiers(self.group_id, "New City")

        self.assertEqual(first, second)
        self.assertEqual(first[0], first[1])
        for value in first:
            self.assertLessEqual(len(value), 63)
            self.assertRegex(value, r"^[a-z][a-z0-9_]+$")
        self.assertIn(uuid.UUID(self.group_id).hex[:8], first[0])

    def test_secret_reference_uses_approved_resolver_format_without_secret_value(self):
        secret_id, reference = build_tenant_secret_reference(self.group_id)

        self.assertEqual(
            secret_id,
            f"geoflow/tenant-db/{self.group_id}/password",
        )
        self.assertEqual(
            reference,
            f"{SECRET_REFERENCE_PREFIX}{secret_id}#password",
        )
        self.assertNotIn("password=", reference)

    def test_existing_tenant_is_hard_blocked(self):
        snapshot = TenantProvisioningSnapshot(
            group_id=self.group_id,
            group_code="new-city",
            group_status="active",
            existing_config_present=True,
            identifier_conflict=False,
        )
        with self.assertRaises(TenantProvisioningContractError) as caught:
            build_tenant_provisioning_plan(
                snapshot,
                db_host="db.internal.example",
                db_port="5432",
                provisioning_enabled=True,
                provisioner_ready=True,
                secret_reference_runtime_required=True,
            )
        self.assertEqual(caught.exception.code, "existing_tenant_protected")

    def test_inactive_group_is_blocked(self):
        snapshot = TenantProvisioningSnapshot(
            group_id=self.group_id,
            group_code="new-city",
            group_status="inactive",
            existing_config_present=False,
            identifier_conflict=False,
        )
        with self.assertRaises(TenantProvisioningContractError) as caught:
            build_tenant_provisioning_plan(
                snapshot,
                db_host="db.internal.example",
                db_port="5432",
                provisioning_enabled=True,
                provisioner_ready=True,
                secret_reference_runtime_required=True,
            )
        self.assertEqual(caught.exception.code, "group_not_active")

    def test_identifier_collision_is_blocked(self):
        snapshot = TenantProvisioningSnapshot(
            group_id=self.group_id,
            group_code="new-city",
            group_status="active",
            existing_config_present=False,
            identifier_conflict=True,
        )
        with self.assertRaises(TenantProvisioningContractError) as caught:
            build_tenant_provisioning_plan(
                snapshot,
                db_host="db.internal.example",
                db_port="5432",
                provisioning_enabled=True,
                provisioner_ready=True,
                secret_reference_runtime_required=True,
            )
        self.assertEqual(caught.exception.code, "tenant_identifier_conflict")

    def test_plan_does_not_enable_execution_merely_because_prerequisites_are_ready(self):
        plan = self._plan(
            provisioning_enabled=True,
            provisioner_ready=True,
            secret_reference_runtime_required=True,
        )

        self.assertTrue(plan.execution_prerequisites_ready)
        self.assertFalse(plan.execution_available)
        self.assertTrue(plan.runtime_secret_grant_required)

    def test_plan_reports_disabled_feature_without_mutation(self):
        plan = self._plan(provisioning_enabled=False)

        self.assertFalse(plan.provisioning_enabled)
        self.assertFalse(plan.execution_prerequisites_ready)
        self.assertFalse(plan.execution_available)

    def test_invalid_provisioner_port_is_not_ready(self):
        plan = self._plan(db_port="not-a-port")

        self.assertEqual(plan.db_port, 0)
        self.assertFalse(plan.provisioner_ready)

    def test_execution_sequence_publishes_group_config_last(self):
        self.assertEqual(PROVISIONING_EXECUTION_SEQUENCE[-1], "publish_group_db_config_last")
        self.assertLess(
            PROVISIONING_EXECUTION_SEQUENCE.index("create_external_secret"),
            PROVISIONING_EXECUTION_SEQUENCE.index("grant_runtime_role_exact_secret_read"),
        )
        self.assertLess(
            PROVISIONING_EXECUTION_SEQUENCE.index("grant_runtime_role_exact_secret_read"),
            PROVISIONING_EXECUTION_SEQUENCE.index("verify_runtime_secret_resolution_and_db_connectivity"),
        )

    def test_rollback_contract_only_targets_attempt_owned_unpublished_resources(self):
        self.assertIn("drop_new_database_only_if_created_by_attempt", PROVISIONING_ROLLBACK_SEQUENCE)
        self.assertIn("drop_new_database_role_only_if_created_by_attempt", PROVISIONING_ROLLBACK_SEQUENCE)
        self.assertNotIn("delete_group_db_config", PROVISIONING_ROLLBACK_SEQUENCE)

    @override_settings(
        CENTRAL_DB_ALIAS="default",
        PROVISIONER_DB_HOST="db.internal.example",
        PROVISIONER_DB_PORT="5432",
        ENABLE_TENANT_PROVISIONING=False,
        PROVISIONING_READY=True,
        TENANT_DB_REQUIRE_SECRET_REFERENCES=True,
    )
    def test_inspector_reads_metadata_but_never_executes(self):
        group = MagicMock()
        group.id = uuid.UUID(self.group_id)
        group.code = "new-city"
        group.status = "active"

        group_query = MagicMock()
        group_query.filter.return_value.only.return_value.first.return_value = group
        existing_query = MagicMock()
        existing_query.filter.return_value.exists.return_value = False

        conflict_chain = MagicMock()
        conflict_chain.filter.return_value.exclude.return_value.exists.return_value = False

        with patch(
            "control.services.tenant_provisioning_contract.Group.objects.using",
            return_value=group_query,
        ), patch(
            "control.services.tenant_provisioning_contract.GroupDBConfig.objects.using",
            side_effect=[existing_query, conflict_chain],
        ):
            plan = inspect_tenant_provisioning_plan(self.group_id)

        self.assertEqual(plan.group_id, self.group_id)
        self.assertFalse(plan.provisioning_enabled)
        self.assertFalse(plan.execution_available)
        self.assertTrue(plan.runtime_secret_grant_required)
