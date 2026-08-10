from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "phase1-application-deploy.yml"


class Phase1ApplicationDeployExactShaContractTests(TestCase):
    def _text(self) -> str:
        return WORKFLOW.read_text()

    def test_production_deploy_is_exact_sha_and_guarded(self):
        text = self._text()
        self.assertIn("environment: production", text)
        self.assertIn('ref: ${{ github.sha }}', text)
        self.assertIn('test "$GITHUB_REF_NAME" = "release/stabilized-deploy"', text)
        self.assertIn('test "$candidate_sha" = "$GITHUB_SHA"', text)
        self.assertIn("candidate_sha_not_current_release_head", text)

    def test_atomic_contract_runtime_changes_trigger_deploy(self):
        text = self._text()
        self.assertIn("geoflow_ops/security_views.py", text)
        self.assertIn("geoflow_ops/services/contract_project_pair.py", text)

    def test_deploy_keeps_health_checks_and_rollback(self):
        text = self._text()
        self.assertIn("rollback_started=yes", text)
        self.assertIn("stabilized_service_failed_post_restart_healthcheck", text)
        self.assertIn("public_root_unhealthy_after_deploy", text)
        self.assertIn("public_terms_not_200_after_deploy", text)
        self.assertIn("public_privacy_not_200_after_deploy", text)

    def test_does_not_dump_runtime_secrets(self):
        text = self._text().lower()
        for forbidden in (
            "cat .env",
            "printenv",
            "env |",
            "set -x",
        ):
            self.assertNotIn(forbidden, text)
