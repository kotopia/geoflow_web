from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "iroomsng-unit-owner-diagnostic.yml"


class IroomsngUnitOwnerDiagnosticContractTests(TestCase):
    def _text(self) -> str:
        return WORKFLOW.read_text()

    def test_runs_once_on_reviewed_release_and_is_production_gated(self):
        text = self._text()
        self.assertIn("push:", text)
        self.assertIn("release/stabilized-deploy", text)
        self.assertIn("iroomsng-unit-owner-diagnostic.yml", text)
        self.assertNotIn("pull_request:", text)
        self.assertIn("environment: production", text)
        self.assertIn('test "$(git rev-parse HEAD)" = "$GITHUB_SHA"', text)

    def test_nginx_target_is_derived_without_printing_config(self):
        text = self._text()
        self.assertIn("sudo -n nginx -T", text)
        self.assertIn("single_loopback_upstream_not_proven", text)
        self.assertIn("server_name", text)
        self.assertIn("iroomsng", text)
        self.assertIn("proxy_pass", text)
        self.assertNotIn('cat "$nginx_dump"', text)
        self.assertNotIn("tee $nginx_dump", text)

    def test_only_service_basenames_and_bounded_state_are_reported(self):
        text = self._text()
        self.assertIn("basename \"$service_file\"", text)
        self.assertIn("iroomsng_owner_candidate_units=", text)
        self.assertIn("iroomsng_owner_unit=", text)
        self.assertIn("iroomsng_owner_active_state=", text)
        self.assertIn("iroomsng_owner_sub_state=", text)
        self.assertIn("iroomsng_owner_unit_file_state=", text)
        self.assertIn("iroomsng_owner_working_directory_exists=", text)
        self.assertIn("iroomsng_owner_execstart_targets_upstream=", text)
        self.assertNotIn('echo "$working_directory"', text)
        self.assertNotIn('echo "$exec_start"', text)
        self.assertNotIn("-p Environment", text)
        self.assertNotIn("-p EnvironmentFiles", text)

    def test_known_geoflow_units_are_explicitly_forbidden(self):
        text = self._text()
        self.assertIn("geoflow-stabilized.service|geoflow.service|gunicorn.service", text)
        self.assertIn("iroomsng_owner_forbidden_geoflow_unit=yes", text)

    def test_diagnostic_has_no_service_or_nginx_mutation(self):
        text = self._text().lower()
        for forbidden in (
            "systemctl restart",
            "systemctl start",
            "systemctl stop",
            "systemctl enable",
            "systemctl disable",
            "systemctl mask",
            "nginx -s reload",
            "systemctl reload",
            "service restart",
            "service start",
            "service stop",
            "kill -",
            "pkill",
            "git reset",
            "git checkout -b",
            "aws s3",
            "ps aux",
            "pgrep",
            "printenv",
            "cat .env",
            "journalctl",
        ):
            self.assertNotIn(forbidden, text)

    def test_ambiguous_ownership_fails_closed_without_recovery(self):
        text = self._text()
        self.assertIn('if [ "$candidate_count" -ne 1 ]', text)
        self.assertIn("iroomsng_owner_unique_unit=no", text)
        self.assertIn("iroomsng_unit_owner_diagnostic_complete=yes", text)
        self.assertNotIn("recovery", text.lower())
