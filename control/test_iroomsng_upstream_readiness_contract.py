from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "iroomsng-upstream-readiness-diagnostic.yml"
LAUNCHER = ROOT / ".github" / "workflows" / "iroomsng-upstream-readiness-launcher.yml"


class IroomsngUpstreamReadinessContractTests(TestCase):
    def _text(self) -> str:
        return WORKFLOW.read_text()

    def _launcher(self) -> str:
        return LAUNCHER.read_text()

    def test_diagnostic_is_manual_reusable_release_only_and_production_gated(self):
        text = self._text()
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("workflow_call:", text)
        self.assertNotIn("\n  push:\n", text)
        self.assertNotIn("\n  pull_request:\n", text)
        self.assertIn("github.ref_name == 'release/stabilized-deploy'", text)
        self.assertIn("environment: production", text)
        self.assertIn('test "$(git rev-parse HEAD)" = "$GITHUB_SHA"', text)

    def test_launcher_creates_one_gated_run_only_when_its_own_file_changes(self):
        text = self._launcher()
        self.assertIn("\n  push:\n", text)
        self.assertIn("      - release/stabilized-deploy", text)
        self.assertIn(
            "      - .github/workflows/iroomsng-upstream-readiness-launcher.yml",
            text,
        )
        self.assertNotIn("workflow_dispatch:", text)
        self.assertIn(
            "uses: ./.github/workflows/iroomsng-upstream-readiness-diagnostic.yml",
            text,
        )
        self.assertIn('ssh_port: "22"', text)
        self.assertIn("secrets: inherit", text)
        self.assertNotIn("environment: production", text)

    def test_remote_probe_is_read_only_and_never_prints_nginx_dump(self):
        text = self._text()
        for forbidden in (
            "systemctl restart",
            "systemctl stop",
            "systemctl start",
            "nginx -s reload",
            "git reset",
            "git checkout",
            "git pull",
            "sed -i",
            "scp ",
            "put_object",
            "upload_file",
            "aws s3",
        ):
            self.assertNotIn(forbidden, text)
        self.assertIn('sudo -n nginx -T >"$nginx_dump" 2>/dev/null', text)
        self.assertNotIn('cat "$nginx_dump"', text)

    def test_probe_accepts_only_one_loopback_http_upstream_for_iroomsng(self):
        text = self._text()
        self.assertIn(r"server_name\s+[^;]*\biroomsng\.kr\b", text)
        self.assertIn(r"proxy_pass\s+http://127\.0\.0\.1:(\d{1,5})", text)
        self.assertIn("len(unique) != 1", text)
        self.assertIn("iroomsng_diag_single_loopback_upstream=yes", text)

    def test_probe_reports_listener_and_local_http_shape_without_process_or_env_dump(self):
        text = self._text()
        self.assertIn("ss -ltnH", text)
        self.assertIn("iroomsng_diag_upstream_listener=yes", text)
        self.assertIn("iroomsng_diag_upstream_listener=no", text)
        self.assertIn("--header 'Host: iroomsng.kr'", text)
        self.assertIn("iroomsng_diag_local_upstream_http_reachable=", text)
        self.assertNotIn("ss -ltnp", text)
        self.assertNotIn("printenv", text)
        self.assertNotIn("/proc/", text)

    def test_public_probe_is_get_only(self):
        text = self._text()
        self.assertIn("https://iroomsng.kr/", text)
        self.assertNotIn("--request POST", text)
        self.assertNotIn("--data", text)
        self.assertNotIn("--form", text)
