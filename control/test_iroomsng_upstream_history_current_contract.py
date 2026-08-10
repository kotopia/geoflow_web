from pathlib import Path
from unittest import TestCase

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "iroomsng-upstream-history-current.yml"


class IroomsngUpstreamHistoryCurrentContractTests(TestCase):
    def _text(self) -> str:
        return WORKFLOW.read_text()

    def test_exact_trigger_sha_and_production_gate(self):
        text = self._text()
        self.assertIn("environment: production", text)
        self.assertIn("ref: ${{ github.sha }}", text)
        self.assertIn('test "$GITHUB_REF_NAME" = "release/stabilized-deploy"', text)
        self.assertIn('test "$(git rev-parse HEAD)" = "$GITHUB_SHA"', text)

    def test_is_read_only_and_does_not_emit_sensitive_runtime_data(self):
        text = self._text().lower()
        for forbidden in (
            "systemctl restart",
            "systemctl start",
            "systemctl stop",
            "systemctl reload",
            "nginx -s reload",
            "service restart",
            "service start",
            "service stop",
            "aws s3",
            "ps aux",
            "printenv",
            "cat .env",
            'echo "$exec_start"',
            'cat "$nginx_dump"',
        ):
            self.assertNotIn(forbidden, text)

    def test_reports_only_bounded_upstream_history(self):
        text = self._text()
        self.assertIn("iroomsng_current_same_upstream_as_geoflow=", text)
        self.assertIn("iroomsng_current_listener_present=", text)
        self.assertIn("iroomsng_current_historical_alternate_port_count=", text)
        self.assertIn("iroomsng_current_historical_alternate_listener_count=", text)
        self.assertIn("iroomsng_current_public_root_code=", text)
