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

    def _script(self) -> str:
        return (
            Path(__file__).parent.parent
            / "scripts"
            / "ops"
            / "account_security_production_rollout.sh"
        ).read_text(encoding="utf-8")

    def test_rollout_is_manual_and_production_gated(self):
        workflow = self._workflow()
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("\n  push:", workflow)
        self.assertIn("environment: production", workflow)
        self.assertIn("REQUESTED_RELEASE_SHA", workflow)
        self.assertIn("release_sha_not_current_head", workflow)
        self.assertIn("bash -n scripts/ops/account_security_production_rollout.sh", workflow)
        self.assertIn("REMOTE_STAGE", workflow)

    def test_rollout_reconciles_only_dirty_files_matching_reviewed_candidate(self):
        script = self._script()
        self.assertIn("production_worktree_has_unreviewed_status", script)
        self.assertIn("production_dirty_file_diverges_from_candidate", script)
        self.assertIn("dirty_files_match_candidate=yes", script)
        self.assertNotIn("git clean", script)

    def test_migration_scope_is_bounded_and_schema_is_audited(self):
        script = self._script()
        self.assertIn("0004_signup_verification_delivery_outbox", script)
        self.assertIn("0005_join_request_decision_audit_columns", script)
        self.assertIn("0006_account_password_reset_schema", script)
        self.assertIn("unexpected_migration_in_plan", script)
        self.assertIn(
            "manage.py migrate control 0006_account_password_reset_schema --database=default --noinput",
            script,
        )
        self.assertIn("manage.py check_account_password_reset_schema --strict", script)

    def test_public_smoke_preserves_auth_and_csrf_boundaries(self):
        script = self._script()
        self.assertIn("https://geoflow.co.kr/password/forgot/", script)
        self.assertIn("https://geoflow.co.kr/password/reset/", script)
        self.assertIn("https://geoflow.co.kr/control/account/password/change/", script)
        self.assertIn("forgot_post_without_csrf", script)
        self.assertIn("reset_post_without_csrf", script)
        self.assertIn("password_change_auth_boundary_regressed", script)

    def test_application_rollback_retains_additive_database_migrations(self):
        script = self._script()
        self.assertIn("account_rollout_rollback_database_additive_migrations_retained=yes", script)
        self.assertIn("account_rollout_rollback_completed=yes", script)

    def test_script_never_prints_environment_or_secret_values(self):
        script = self._script()
        forbidden = ("cat .env", "cat \"$repo/.env\"", "printenv", "env |", "set -x")
        for fragment in forbidden:
            self.assertNotIn(fragment, script)


if __name__ == "__main__":
    unittest.main()
