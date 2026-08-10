from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "iroomsng-worker-boot-cause-diagnostic.yml"


class IroomsngWorkerBootCauseContractTests(TestCase):
    def _text(self) -> str:
        return WORKFLOW.read_text()

    def test_is_exact_sha_and_production_gated(self):
        text = self._text()
        self.assertIn("environment: production", text)
        self.assertIn('ref: ${{ github.sha }}', text)
        self.assertIn('test "$GITHUB_REF_NAME" = "release/stabilized-deploy"', text)
        self.assertIn('test "$(git rev-parse HEAD)" = "$GITHUB_SHA"', text)

    def test_emits_only_bounded_failure_taxonomy(self):
        text = self._text()
        for required in (
            "_primary_category=",
            "django_improperly_configured",
            "database_operational",
            "database_connection",
            "module_import",
            "python_syntax",
            "python_runtime",
            "worker_timeout",
            "worker_boot",
            "units_same_working_directory=",
            "units_same_user=",
            "_has_django_settings_module=",
            "_has_environment_file=",
        ):
            self.assertIn(required, text)

        for forbidden in (
            'print(text)',
            'echo "$wd"',
            'echo "$unit_user"',
            'echo "$exec_start"',
            'cat "$journal_file"',
            'tail "$journal_file"',
            'head "$journal_file"',
        ):
            self.assertNotIn(forbidden, text)

    def test_has_no_production_mutation_or_sensitive_dump(self):
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
            "git checkout",
            "kill -",
            "pkill",
            "aws s3",
            "aws secretsmanager",
            "printenv",
            "env |",
            "cat .env",
            "-p environment ",
            "-p environmentfiles",
            "ps aux",
            "ps -ef",
        ):
            self.assertNotIn(forbidden, text)

    def test_merge_trigger_is_narrow(self):
        text = self._text()
        self.assertIn("push:", text)
        self.assertIn("branches:\n      - release/stabilized-deploy", text)
        self.assertIn("- .github/workflows/iroomsng-worker-boot-cause-diagnostic.yml", text)
