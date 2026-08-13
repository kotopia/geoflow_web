from __future__ import annotations

from pathlib import Path
import unittest


WORKFLOW = (
    Path(__file__).resolve().parent.parent
    / ".github"
    / "workflows"
    / "phase2-aws-admin-capability-diagnostic.yml"
)


class Phase2AwsAdminCapabilityContractTests(unittest.TestCase):
    def _source(self) -> str:
        return WORKFLOW.read_text(encoding="utf-8")

    def test_diagnostic_is_exact_release_and_production_gated(self):
        source = self._source()
        self.assertIn("- release/stabilized-deploy", source)
        self.assertIn("environment: production", source)
        self.assertIn('test "$(git rev-parse HEAD)" = "$GITHUB_SHA"', source)
        self.assertIn("StrictHostKeyChecking=yes", source)

    def test_diagnostic_uses_only_read_or_simulation_aws_operations(self):
        source = self._source()
        required_read_operations = (
            "get_caller_identity",
            "describe_instances",
            "describe_iam_instance_profile_associations",
            "list_roles",
            "list_instance_profiles",
            "list_policies",
            "simulate_principal_policy",
        )
        for operation in required_read_operations:
            self.assertIn(operation, source)

        forbidden_mutations = (
            "create_role(",
            "create_policy(",
            "create_instance_profile(",
            "add_role_to_instance_profile(",
            "attach_role_policy(",
            "put_role_policy(",
            "associate_iam_instance_profile(",
            "replace_iam_instance_profile_association(",
            "disassociate_iam_instance_profile(",
            "delete_role(",
            "delete_policy(",
            "delete_instance_profile(",
            "terminate_instances(",
            "modify_instance_attribute(",
        )
        for mutation in forbidden_mutations:
            self.assertNotIn(mutation, source)

    def test_diagnostic_never_emits_sensitive_identifiers(self):
        source = self._source()
        self.assertIn("never prints credential values", source)
        self.assertNotIn("print(caller_arn", source)
        self.assertNotIn("print(instance_id", source)
        self.assertNotIn("print(credentials", source)
        self.assertNotIn("get_frozen_credentials", source)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY)", source)
        self.assertNotIn("AWS_ACCESS_KEY_ID)", source)

    def test_diagnostic_reports_only_capability_classes(self):
        source = self._source()
        expected_markers = (
            "phase2_admin_existing_credentials_available=",
            "phase2_admin_existing_credential_class=",
            "phase2_admin_sts_identity=",
            "phase2_admin_principal_class=",
            "phase2_admin_instance_identity=",
            "phase2_admin_ec2_describe_own_instance=",
            "phase2_admin_current_instance_profile=",
            "phase2_admin_ec2_profile_association_read=",
            "phase2_admin_iam_inventory_read=",
            "phase2_admin_required_mutation_simulation=",
            "phase2_admin_capability_candidate=",
            "phase2_aws_admin_capability_diagnostic_complete=yes",
        )
        for marker in expected_markers:
            self.assertIn(marker, source)


if __name__ == "__main__":
    unittest.main()
