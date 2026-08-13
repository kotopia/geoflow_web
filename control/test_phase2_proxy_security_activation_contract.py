from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/phase2-proxy-security-staged-activation.yml"


class Phase2ProxySecurityActivationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_manual_release_and_production_gate_are_required(self):
        text = self.text
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("github.ref_name == 'release/stabilized-deploy'", text)
        self.assertIn("environment: production", text)
        self.assertIn('test "$(git rev-parse HEAD)" = "$GITHUB_SHA"', text)
        self.assertIn("PHASE2_PROXY_ACTIVATE", text)

    def test_activation_is_one_stage_at_a_time_in_fixed_order(self):
        text = self.text
        for stage in ("trust-proxy", "ssl-redirect", "short-hsts"):
            self.assertIn(f"- {stage}", text)
        self.assertIn("trust-proxy:0,0,0,0,0", text)
        self.assertIn("ssl-redirect:1,0,0,0,0", text)
        self.assertIn("short-hsts:1,1,0,0,0", text)
        self.assertIn("trust-proxy:1,0,0,0,0", text)
        self.assertIn("ssl-redirect:1,1,0,0,0", text)
        self.assertIn("short-hsts:1,1,300,0,0", text)

    def test_proxy_and_runtime_code_must_match_reviewed_blobs(self):
        text = self.text
        self.assertIn("expected_settings_blob=", text)
        self.assertIn("expected_proxy_settings_blob=", text)
        self.assertIn("runtime_settings_not_reviewed", text)
        self.assertIn("runtime_proxy_settings_not_reviewed", text)
        self.assertIn("sudo -n nginx -T", text)
        self.assertIn("X-Forwarded-Proto", text)
        self.assertIn("forwarded_proto_not_proven", text)

    def test_only_short_hsts_is_enabled_and_broad_flags_stay_off(self):
        text = self.text
        self.assertIn("'short-hsts': ('1', '1', '300')", text)
        self.assertIn("'DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS': '0'", text)
        self.assertIn("'DJANGO_SECURE_HSTS_PRELOAD': '0'", text)
        self.assertNotIn("'DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS': '1'", text)
        self.assertNotIn("'DJANGO_SECURE_HSTS_PRELOAD': '1'", text)
        self.assertIn("max-age=300", text)

    def test_mutation_is_limited_to_runtime_env_and_service_restart(self):
        text = self.text
        self.assertIn("runtime_env_updated=yes", text)
        self.assertIn('sudo -n systemctl restart "$service"', text)
        self.assertNotIn("systemctl restart nginx", text)
        self.assertNotIn("systemctl reload nginx", text)
        self.assertNotIn("nginx -s reload", text)
        self.assertNotIn("git pull", text)
        self.assertNotIn("git reset", text)
        self.assertNotIn("manage.py migrate", text)

    def test_public_pre_and_post_checks_are_mandatory(self):
        text = self.text
        self.assertIn("http_not_redirecting_before_mutation", text)
        self.assertIn("https_login_unhealthy_before_mutation", text)
        self.assertIn("http_not_redirecting_after_mutation", text)
        self.assertIn("https_login_unhealthy_after_mutation", text)
        self.assertIn("short_hsts_header_not_expected", text)

    def test_backup_survives_until_runner_smoke_and_failure_rolls_back(self):
        text = self.text
        self.assertIn("/tmp/geoflow-phase2-proxy-${BACKUP_TOKEN}.env", text)
        self.assertIn("retain rollback backup", text)
        self.assertIn("Finalize successful activation", text)
        self.assertIn("if: failure()", text)
        self.assertIn("Roll back if any post-mutation step failed", text)
        self.assertIn("phase2_proxy_activation_rollback_completed=yes", text)
        self.assertIn("rollback_backup_missing_at_finalize", text)

    def test_workflow_does_not_print_sensitive_runtime_configuration(self):
        text = self.text
        forbidden = (
            "cat $repo/.env",
            'cat "$repo/.env"',
            "cat .env",
            "printenv",
            "env |",
            "set -x",
        )
        for item in forbidden:
            with self.subTest(item=item):
                self.assertNotIn(item, text)


if __name__ == "__main__":
    unittest.main()
