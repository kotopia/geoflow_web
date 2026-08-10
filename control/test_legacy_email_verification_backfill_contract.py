from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "legacy-email-verification-backfill.yml"


class LegacyEmailVerificationBackfillContractTests(TestCase):
    def _text(self) -> str:
        return WORKFLOW.read_text()

    def test_backfill_is_release_push_only_and_production_gated(self):
        text = self._text()
        self.assertIn("push:", text)
        self.assertIn("release/stabilized-deploy", text)
        self.assertNotIn("pull_request:", text)
        self.assertIn("environment: production", text)
        self.assertIn('test "$(git rev-parse HEAD)" = "$GITHUB_SHA"', text)

    def test_legacy_candidate_definition_is_conservative(self):
        text = self._text()
        self.assertIn('MIGRATION_NAME = "0002_signup_core_schema"', text)
        self.assertIn("u.created_at < %s", text)
        self.assertIn("u.is_active = TRUE", text)
        self.assertIn("u.email_verified = FALSE", text)
        self.assertIn("NOT EXISTS", text)
        self.assertIn("FROM signup_requests sr", text)
        self.assertIn("FROM user_group_map ugm", text)
        self.assertIn("ugm.status = 'active'", text)
        self.assertIn("lower(trim(COALESCE(g.status, ''))) = 'active'", text)
        self.assertIn("pbkdf2_sha256$%%", text)
        self.assertIn("bcrypt_sha256$%%", text)

    def test_backfill_is_bounded_locked_and_transactional(self):
        text = self._text()
        self.assertIn("MAX_CANDIDATES = 100", text)
        self.assertIn("candidate_limit_exceeded", text)
        self.assertIn("transaction.atomic(using=\"default\")", text)
        self.assertIn("FOR UPDATE", text)
        self.assertIn("candidate_set_changed", text)
        self.assertIn("update_count_mismatch", text)
        self.assertIn("postcheck_failed", text)

    def test_only_email_verified_and_updated_at_are_mutated(self):
        text = self._text()
        update_block = text.split("UPDATE users", 1)[1].split("RETURNING id", 1)[0]
        self.assertIn("SET email_verified = TRUE", update_block)
        self.assertIn("updated_at = now()", update_block)
        self.assertNotIn("password_hash =", update_block)
        self.assertNotIn("is_active =", update_block)
        for forbidden in (
            "DELETE FROM users",
            "UPDATE user_group_map",
            "UPDATE groups",
            "UPDATE group_db_config",
            "systemctl restart",
            "systemctl stop",
            "systemctl start",
            "nginx -s reload",
            "aws s3",
        ):
            self.assertNotIn(forbidden, text)

    def test_workflow_never_prints_identity_or_secret_values(self):
        text = self._text()
        self.assertNotIn("SELECT u.email", text)
        self.assertNotIn("print(email", text)
        self.assertNotIn("print(password", text)
        self.assertNotIn("printenv", text)
        self.assertNotIn("cat .env", text)
        self.assertIn("legacy_email_verification_backfill_complete=yes", text)
