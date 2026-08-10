from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "cheonan-central-metadata-remediation.yml"


class CheonanMetadataRemediationContractTests(TestCase):
    def _text(self) -> str:
        return WORKFLOW.read_text()

    def test_remediation_is_release_only_and_production_gated(self):
        text = self._text()
        self.assertIn("branches:\n      - release/stabilized-deploy", text)
        self.assertIn("environment: production", text)
        self.assertIn('test "$(git rev-parse HEAD)" = "$GITHUB_SHA"', text)

    def test_remediation_preserves_password_and_uses_runtime_static_metadata(self):
        text = self._text()
        self.assertIn('TARGET_ALIAS = "cheonan_db"', text)
        self.assertIn('static = settings.DATABASES.get(TARGET_ALIAS)', text)
        self.assertIn("resolve_tenant_db_password(stored_password)", text)
        self.assertIn("stored_password_not_static_match", text)
        self.assertNotIn("SET db_password", text)
        self.assertIn("cheonan_remediation_password_preserved=yes", text)

    def test_remediation_requires_existing_authorization_shape(self):
        text = self._text()
        self.assertIn("no_active_membership", text)
        self.assertIn("no_active_verified_membership", text)
        self.assertIn("permissionless_active_role", text)
        self.assertIn("group_already_active_unexpected", text)
        self.assertIn("metadata_mismatch_not_present", text)

    def test_remediation_is_transactional_and_connection_verified(self):
        text = self._text()
        self.assertIn('transaction.atomic(using="default")', text)
        self.assertIn("FOR UPDATE OF c, g", text)
        self.assertGreaterEqual(text.count("connect_ok("), 3)
        self.assertIn("remediated_config_not_connectable", text)
        self.assertIn("post_commit_metadata_verification_failed", text)
        self.assertIn("cheonan_central_metadata_remediation_complete=yes", text)

    def test_remediation_does_not_restart_services_or_touch_unrelated_infrastructure(self):
        text = self._text()
        for forbidden in (
            "systemctl restart",
            "systemctl stop",
            "systemctl start",
            "nginx -s reload",
            "git reset",
            "git pull",
            "put_object",
            "upload_file",
            "aws s3",
        ):
            self.assertNotIn(forbidden, text)
