from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "iroomsng-listener-attribution-diagnostic.yml"


class IroomsngListenerAttributionContractTests(TestCase):
    def _text(self) -> str:
        return WORKFLOW.read_text()

    def test_is_single_run_release_push_and_production_gated(self):
        text = self._text()
        self.assertIn("push:", text)
        self.assertIn("release/stabilized-deploy", text)
        self.assertIn("iroomsng-listener-attribution-diagnostic.yml", text)
        self.assertNotIn("pull_request:", text)
        self.assertIn("environment: production", text)
        self.assertIn('test "$(git rev-parse HEAD)" = "$GITHUB_SHA"', text)

    def test_derives_nginx_upstream_without_printing_config(self):
        text = self._text()
        self.assertIn("sudo -n nginx -T", text)
        self.assertIn("server_name", text)
        self.assertIn("iroomsng", text)
        self.assertIn("proxy_pass", text)
        self.assertNotIn('cat "$nginx_dump"', text)
        self.assertNotIn('echo "$nginx_dump"', text)

    def test_socket_and_cgroup_details_are_bounded(self):
        text = self._text()
        self.assertIn("sudo -n ss -ltnpH", text)
        self.assertIn("/proc/{pid}/cgroup", text)
        self.assertIn("iroomsng_listener_pid_count=", text)
        self.assertIn("iroomsng_listener_cgroup_unit_count=", text)
        self.assertIn("iroomsng_listener_cgroup_unit=", text)
        self.assertNotIn("iroomsng_listener_pid=", text)
        self.assertNotIn("ps aux", text)
        self.assertNotIn("pgrep", text)
        self.assertNotIn("journalctl", text)
        self.assertNotIn("-p Environment", text)
        self.assertNotIn("-p EnvironmentFiles", text)

    def test_direct_http_probes_only_report_status_codes(self):
        text = self._text()
        self.assertIn("Host: ${host_header}", text)
        self.assertIn("iroomsng_listener_direct_iroomsng_code=", text)
        self.assertIn("iroomsng_listener_direct_geoflow_code=", text)
        self.assertIn("--output /dev/null", text)

    def test_has_no_service_nginx_db_or_s3_mutation(self):
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
            "aws s3",
            "manage.py migrate",
            "psql ",
            "printenv",
            "cat .env",
        ):
            self.assertNotIn(forbidden, text)

    def test_known_geoflow_units_are_only_classified_not_mutated(self):
        text = self._text()
        self.assertIn("geoflow-stabilized.service|geoflow.service|gunicorn.service", text)
        self.assertIn("iroomsng_listener_cgroup_unit_is_geoflow=yes", text)
        self.assertNotIn("restart \"$unit\"", text)
