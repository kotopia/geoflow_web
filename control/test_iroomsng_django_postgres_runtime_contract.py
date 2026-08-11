from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "iroomsng-django-postgres-runtime-diagnostic.yml"


class IroomsngDjangoPostgresRuntimeContractTests(TestCase):
    def _text(self) -> str:
        return WORKFLOW.read_text()

    def test_exact_sha_and_production_gate(self):
        text = self._text()
        self.assertIn("environment: production", text)
        self.assertIn('ref: ${{ github.sha }}', text)
        self.assertIn('test "$GITHUB_REF_NAME" = "release/stabilized-deploy"', text)
        self.assertIn('test "$(git rev-parse HEAD)" = "$GITHUB_SHA"', text)

    def test_reports_only_bounded_compatibility_signals(self):
        text = self._text()
        for required in (
            "postgresql_14_minimum_error",
            "django_database_version_check_frame",
            "postgresql_found_major=",
            "not_supported_count=",
            "django_version=",
            "django_probe=",
            "exec_virtualenv=",
        ):
            self.assertIn(required, text)

        for forbidden in (
            'cat "$journal_file"',
            'echo "$exec_raw"',
            'echo "$exec_path"',
            'echo "$runtime_python"',
            'echo "$first_line"',
            'print(text)',
        ):
            self.assertNotIn(forbidden, text)

    def test_has_no_production_mutation_or_database_access(self):
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
            "psql ",
            "pg_isready",
            "select version(",
            "printenv",
            "cat .env",
            "-p environment ",
            "-p environmentfiles",
            "ps aux",
            "ps -ef",
        ):
            self.assertNotIn(forbidden, text)

    def test_push_trigger_is_narrow(self):
        text = self._text()
        self.assertIn("branches:\n      - release/stabilized-deploy", text)
        self.assertIn("- .github/workflows/iroomsng-django-postgres-runtime-diagnostic.yml", text)
