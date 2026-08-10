from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
DIAGNOSTIC = ROOT / ".github" / "workflows" / "phase2-proxy-security-readiness-diagnostic.yml"


class Phase2ProxySecurityReadinessContractTests(TestCase):
    def _text(self) -> str:
        return DIAGNOSTIC.read_text()

    def test_diagnostic_is_manual_release_only_and_production_gated(self):
        text = self._text()
        self.assertIn("workflow_dispatch:", text)
        self.assertNotIn("\n  push:", text)
        self.assertNotIn("\n  pull_request:", text)
        self.assertIn("github.ref_name == 'release/stabilized-deploy'", text)
        self.assertIn("environment: production", text)
        self.assertIn('test "$(git rev-parse HEAD)" = "$GITHUB_SHA"', text)

    def test_remote_probe_is_read_only(self):
        text = self._text()
        for forbidden in (
            "systemctl restart",
            "systemctl stop",
            "systemctl start",
            "git reset",
            "git checkout",
            "git pull",
            "sed -i",
            "put_object(",
            "delete_object(",
            "create_secret(",
            "update_secret(",
            "scp ",
        ):
            self.assertNotIn(forbidden, text)
        self.assertIn("sudo -n nginx -T", text)
        self.assertIn("phase2_proxy_diag_remote_read_only_complete=yes", text)

    def test_diagnostic_requires_forwarded_proto_without_dumping_proxy_config(self):
        text = self._text()
        self.assertIn("X-Forwarded-Proto", text)
        self.assertIn("$scheme|https", text)
        self.assertIn("phase2_proxy_diag_forwarded_proto_configured=yes", text)
        self.assertIn("phase2_proxy_diag_blocker=forwarded_proto_not_proven", text)
        self.assertIn('sudo -n nginx -T >"$nginx_dump" 2>/dev/null', text)
        self.assertNotIn('cat "$nginx_dump"', text)

    def test_diagnostic_reports_django_tls_shape_without_secret_values(self):
        text = self._text()
        for setting_name in (
            "SECURE_PROXY_SSL_HEADER",
            "SECURE_SSL_REDIRECT",
            "SECURE_HSTS_SECONDS",
            "CSRF_COOKIE_SECURE",
            "SESSION_COOKIE_SECURE",
        ):
            self.assertIn(setting_name, text)
        self.assertIn("HTTP_X_FORWARDED_PROTO", text)
        self.assertIn("phase2_proxy_diag_django_proxy_header=", text)
        self.assertIn("phase2_proxy_diag_ssl_redirect=", text)
        self.assertIn("phase2_proxy_diag_hsts=", text)
        self.assertNotIn("print(os.environ", text)
        self.assertNotIn("print(settings.DATABASES", text)

    def test_public_boundary_requires_http_to_canonical_https_and_healthy_login(self):
        text = self._text()
        self.assertIn("http://geoflow.co.kr/", text)
        self.assertIn("https://geoflow.co.kr/login/", text)
        self.assertIn("http_redirect_not_canonical_https", text)
        self.assertIn("https_login_unhealthy", text)
        self.assertIn("phase2_proxy_diag_public_hsts_header=present", text)
        self.assertIn("phase2_proxy_diag_public_hsts_header=missing", text)
        self.assertIn("phase2_proxy_security_readiness_diagnostic_complete=yes", text)
