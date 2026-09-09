from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class BidInterestProductionDeployContractTests(unittest.TestCase):
    def setUp(self):
        self.workflow = (
            ROOT / ".github" / "workflows" / "production-release-deploy-v2.yml"
        ).read_text(encoding="utf-8")

    def test_g2b_key_uses_environment_secret_and_never_a_literal(self):
        self.assertIn(
            "G2B_API_SERVICE_KEY: ${{ secrets.G2B_API_SERVICE_KEY }}",
            self.workflow,
        )
        self.assertNotIn("serviceKey=", self.workflow)
        self.assertIn("test -n \"$G2B_API_SERVICE_KEY\"", self.workflow)

    def test_secret_transfer_is_file_scoped_and_cleaned(self):
        self.assertIn('umask 077', self.workflow)
        self.assertIn('remote_key="/tmp/geoflow-g2b-$run_id.key"', self.workflow)
        self.assertIn('rm -f "$remote_key" "$env_backup"', self.workflow)
        self.assertNotIn("set -x", self.workflow)

    def test_runtime_env_change_is_atomic_and_rollback_capable(self):
        self.assertIn("tempfile.mkstemp", self.workflow)
        self.assertIn("os.replace(temporary, env_path)", self.workflow)
        self.assertIn('cp -p "$env_backup" "$repo/.env"', self.workflow)
        self.assertIn("production_deploy_v2_env_rollback_completed=yes", self.workflow)

    def test_migration_0036_is_dependency_ordered_and_validated(self):
        self.assertIn(
            "('0036_bid_interest_foundation', '0035_employee_education_career_settings')",
            self.workflow,
        )
        for relation in (
            "bid.filter_values",
            "bid.keyword_rules",
            "bid.notices",
            "bid.notice_revisions",
            "bid.notice_matches",
            "bid.notice_reviews",
            "bid.sync_runs",
        ):
            self.assertIn(relation, self.workflow)
        self.assertIn("bid region seed must contain 17 inactive rows", self.workflow)

    def test_live_g2b_check_does_not_log_the_key(self):
        self.assertIn("production_deploy_v2_g2b_live_ok=yes", self.workflow)
        self.assertIn("G2BClient().fetch_page", self.workflow)
        self.assertNotIn("print(key", self.workflow)


if __name__ == "__main__":
    unittest.main()
