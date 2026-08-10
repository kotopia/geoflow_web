from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "iroomsng-exception-class-diagnostic.yml"


class IroomsngExceptionClassContractTests(TestCase):
    def _text(self) -> str:
        return WORKFLOW.read_text()

    def test_exact_sha_and_production_gate(self):
        text = self._text()
        self.assertIn("environment: production", text)
        self.assertIn('ref: ${{ github.sha }}', text)
        self.assertIn('test "$GITHUB_REF_NAME" = "release/stabilized-deploy"', text)
        self.assertIn('test "$(git rev-parse HEAD)" = "$GITHUB_SHA"', text)

    def test_output_is_allowlisted_classification_only(self):
        text = self._text()
        self.assertIn("allow = {", text)
        self.assertIn("dominant_class=", text)
        self.assertIn("recognized_total=", text)
        self.assertIn("other_terminal_exception=", text)
        self.assertIn("exception_chain_markers=", text)
        self.assertNotIn("print(text)", text)
        self.assertNotIn("print(tokens)", text)
        self.assertNotIn("print(sys.argv[1])", text)
        self.assertNotIn('cat "$journal_file"', text)
        self.assertNotIn('echo "$journal_file"', text)

    def test_no_production_mutation_or_sensitive_dump(self):
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
            "aws secretsmanager",
            "printenv",
            "cat .env",
            "-p environment ",
            "-p environmentfiles",
            "ps aux",
            "ps -ef",
        ):
            self.assertNotIn(forbidden, text)

    def test_merge_trigger_is_single_path(self):
        text = self._text()
        self.assertIn("branches:\n      - release/stabilized-deploy", text)
        self.assertIn("- .github/workflows/iroomsng-exception-class-diagnostic.yml", text)
