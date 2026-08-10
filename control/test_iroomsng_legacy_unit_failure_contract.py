from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "iroomsng-legacy-unit-failure-diagnostic.yml"


class IroomsngLegacyUnitFailureContractTests(TestCase):
    def _text(self) -> str:
        return WORKFLOW.read_text()

    def test_is_exact_sha_and_production_gated(self):
        text = self._text()
        self.assertIn("environment: production", text)
        self.assertIn('ref: ${{ github.sha }}', text)
        self.assertIn('test "$GITHUB_REF_NAME" = "release/stabilized-deploy"', text)
        self.assertIn('test "$(git rev-parse HEAD)" = "$GITHUB_SHA"', text)

    def test_only_emits_bounded_unit_state_and_aggregate_failure_categories(self):
        text = self._text()
        for required in (
            "units_same_fragment=",
            "units_same_execstart=",
            "_working_directory_is_geoflow_repo=",
            "_targets_iroomsng_upstream=",
            "_exec_has_geoflow_project=",
            "_exec_has_iroomsng_marker=",
            "_journal_address_in_use=",
            "_journal_module_import=",
            "_journal_no_such_file=",
            "_journal_permission_denied=",
            "_journal_worker_boot=",
        ):
            self.assertIn(required, text)
        self.assertNotIn('echo "$exec_start"', text)
        self.assertNotIn('echo "$wd"', text)
        self.assertNotIn('echo "$origin"', text)
        self.assertNotIn('cat "$journal_file"', text)

    def test_has_no_production_mutation_or_secret_dump(self):
        text = self._text().lower()
        for forbidden in (
            "systemctl restart",
            "systemctl start",
            "systemctl stop",
            "systemctl reload",
            "systemctl enable",
            "systemctl disable",
            "nginx -s reload",
            "git pull",
            "git reset",
            "kill -",
            "pkill",
            "aws s3",
            "printenv",
            "cat .env",
            "-p environment",
            "-p environmentfiles",
        ):
            self.assertNotIn(forbidden, text)
