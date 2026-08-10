from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "iroomsng-upstream-history-diagnostic.yml"


class IroomsngUpstreamHistoryContractTests(TestCase):
    def _text(self) -> str:
        return WORKFLOW.read_text()

    def test_is_exact_release_and_production_gated(self):
        text = self._text()
        self.assertIn("environment: production", text)
        self.assertIn("release/stabilized-deploy", text)
        self.assertIn('test "$(git rev-parse HEAD)" = "$GITHUB_SHA"', text)

    def test_compares_iroomsng_and_geoflow_without_printing_config(self):
        text = self._text()
        self.assertIn("iroomsng_hist_same_upstream_as_geoflow=", text)
        self.assertIn("iroomsng.kr", text)
        self.assertIn("geoflow.co.kr", text)
        self.assertIn("sudo -n nginx -T", text)
        self.assertNotIn('cat "$nginx_dump"', text)

    def test_known_units_are_only_bounded_booleans_and_state(self):
        text = self._text()
        self.assertIn("geoflow-stabilized.service geoflow.service gunicorn.service", text)
        self.assertIn("_targets_current_port=", text)
        self.assertIn("_active_state=", text)
        self.assertNotIn('echo "$exec_start"', text)
        self.assertNotIn("-p Environment", text)
        self.assertNotIn("-p EnvironmentFiles", text)

    def test_history_and_error_logs_are_aggregate_only(self):
        text = self._text()
        self.assertIn("iroomsng_hist_historical_alternate_port_count=", text)
        self.assertIn("iroomsng_hist_recent_current_port_refused_count=", text)
        self.assertIn("capture_output=True", text)
        self.assertNotIn("print(cp.stdout)", text)
        self.assertNotIn('echo "$error_log_path"', text)

    def test_has_no_production_mutation(self):
        text = self._text().lower()
        for forbidden in (
            "systemctl restart",
            "systemctl start",
            "systemctl stop",
            "systemctl reload",
            "systemctl enable",
            "systemctl disable",
            "nginx -s reload",
            "service restart",
            "service start",
            "service stop",
            "kill -",
            "pkill",
            "git pull",
            "git reset",
            "aws s3",
            "ps aux",
            "printenv",
            "cat .env",
        ):
            self.assertNotIn(forbidden, text)
