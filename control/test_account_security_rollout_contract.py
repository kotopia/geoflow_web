from pathlib import Path
import unittest


class AccountSecurityRolloutContractTests(unittest.TestCase):
    def _workflow(self) -> str:
        return (
            Path(__file__).parent.parent
            / ".github"
            / "workflows"
            / "account-security-production-rollout.yml"
        ).read_text(encoding="utf-8")

    def test_rollout_is_manual_and_production_gated(self):
        workflow = self._workflow()
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("\n  push:", workflow)
        self.assertIn("environment: production", workflow)
        self.assertIn("REQUESTED_RELEASE_SHA", workflow)
        self.assertIn("release_sha_not_current_head", workflow)

    def test_rollout_reconciles_only_dirty_files_matching_reviewed_candidate(self):
        workflow = self._workflow()
        self.assertIn("production_worktree_has_unreviewed_status", workflow)
        self.assertIn("production_dirty_file_diverges_from_candidate", workflow)
        self.assertIn("dirty_files_match_candidate=yes", workflow)
        self.assertNotIn("git clean", workflow)

    def test_migration_scope_is_bounded_and_schema_is_audited(self):
        workflow = self._workflow()
        self.assertIn("0004_signup_verification_delivery_outbox", workflow)
        self.assertIn("0005_join_request_decision_audit_columns", workflow)
        self.assertIn("0006_account_password_reset_schema", workflow)
        self.assertIn("unexpected_migration_in_plan", workflow)
        self.assertIn(
            "manage.py migrate control 0006_account_password_reset_schema --database=default --noinput",
            workflow,
        )
        self.assertIn("manage.py check_account_password_reset_schema --strict", workflow)

    def test_public_smoke_preserves_auth_and_csrf_boundaries(self):
        workflow = self._workflow()
        self.assertIn("https://geoflow.co.kr/password/forgot/", workflow)
        self.assertIn("https://geoflow.co.kr/password/reset/", workflow)
        self.assertIn("https://geoflow.co.kr/control/account/password/change/", workflow)
        self.assertIn("forgot_post_without_csrf", workflow)
        self.assertIn("reset_post_without_csrf", workflow)
        self.assertIn("password_change_auth_boundary_regressed", workflow)

    def test_application_rollback_retains_additive_database_migrations(self):
        workflow = self._workflow()
        self.assertIn("account_rollout_rollback_database_additive_migrations_retained=yes", workflow)
        self.assertIn("account_rollout_rollback_completed=yes", workflow)


if __name__ == "__main__":
    unittest.main()
