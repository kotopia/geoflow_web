from pathlib import Path
from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "phase2-aws-role-min-policy-apply.yml"
APPLICATOR = ROOT / "scripts" / "ops" / "phase2_apply_min_runtime_policy.py"


class Phase2AwsRoleMinPolicyApplyContractTests(SimpleTestCase):
    def test_workflow_is_release_only_and_production_gated(self):
        text = WORKFLOW.read_text()
        self.assertIn("branches:\n      - release/stabilized-deploy", text)
        self.assertIn("environment: production", text)
        self.assertIn("expected_applicator_blob=", text)
        self.assertIn("geoflow-stabilized.service", text)
        self.assertNotIn("iroomsng", text.lower())

    def test_applicator_uses_only_reviewed_runtime_permissions(self):
        text = APPLICATOR.read_text()
        for action in (
            "secretsmanager:GetSecretValue",
            "s3:ListBucket",
            "s3:GetObject",
            "s3:PutObject",
        ):
            self.assertIn(action, text)
        self.assertIn('"s3:prefix": ["tenants/*"]', text)
        self.assertIn('bucket_arn + "/tenants/*"', text)
        self.assertNotIn("s3:DeleteObject", text)
        self.assertNotIn('"Resource": "*"', text)
        self.assertNotIn('"Resource": ["*"]', text)
        self.assertNotIn("create_role(", text)
        self.assertNotIn("attach_role_policy(", text)
        self.assertNotIn("put_user_policy(", text)

    def test_applicator_has_bounded_mutation_and_rollback(self):
        text = APPLICATOR.read_text()
        self.assertIn("iam.put_role_policy(", text)
        self.assertIn("iam.delete_role_policy(", text)
        self.assertIn("phase2_min_policy_rollback=ok", text)
        self.assertIn("phase2_min_policy_apply_complete=yes", text)
        self.assertIn("POLICY_NAME = \"GeoFlowPhase2RuntimeMinimum20260814\"", text)

    def test_post_apply_verification_uses_role_session(self):
        text = APPLICATOR.read_text()
        self.assertIn('method not in {"iam-role", "container-role"}', text)
        self.assertIn('role_session.client("secretsmanager"', text)
        self.assertIn('role_session.client("s3"', text)
        self.assertIn("fallback_s3_", text)
        self.assertIn("fallback_secret_", text)

    def test_identifiers_are_not_printed(self):
        text = APPLICATOR.read_text()
        for unsafe in (
            "print(role_name",
            "print(secret_arn",
            "print(bucket",
            "print(ref.secret_id",
            "print(access_key",
            "print(secret_key",
        ):
            self.assertNotIn(unsafe, text)
