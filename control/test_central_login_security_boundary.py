from pathlib import Path
from unittest import TestCase

CONTROL_DIR = Path(__file__).resolve().parent


class CentralLoginSecurityBoundaryTests(TestCase):
    def test_login_view_masks_credentials_in_error_reports(self):
        source = (CONTROL_DIR / "views_auth.py").read_text(encoding="utf-8")
        self.assertIn(
            '@sensitive_post_parameters("email", "username", "password")',
            source,
        )
        self.assertIn(
            '@sensitive_variables("email", "pw", "pw_hash", "new_hash")',
            source,
        )

    def test_password_verifier_marks_secret_inputs_sensitive(self):
        source = (
            CONTROL_DIR / "services/central_login_authentication.py"
        ).read_text(encoding="utf-8")
        self.assertIn('@sensitive_variables("password")', source)
        self.assertIn(
            '@sensitive_variables("password", "encoded_password", "encoded")',
            source,
        )

    def test_login_form_double_submit_guard_has_matching_form_id(self):
        source = (
            CONTROL_DIR / "templates/control/login.html"
        ).read_text(encoding="utf-8")
        self.assertIn('id="loginForm"', source)
        self.assertIn("getElementById('loginForm')", source)

    def test_login_template_has_one_error_surface_and_no_dead_controls(self):
        source = (
            CONTROL_DIR / "templates/control/login.html"
        ).read_text(encoding="utf-8")
        self.assertEqual(source.count("{% if error %}"), 1)
        self.assertNotIn('name="remember-me"', source)
        self.assertNotIn('href="#">비밀번호 찾기', source)
        self.assertNotIn("demo.adminkit.io", source)

    def test_login_fields_use_browser_credential_autocomplete_contract(self):
        source = (
            CONTROL_DIR / "templates/control/login.html"
        ).read_text(encoding="utf-8")
        self.assertIn('autocomplete="username"', source)
        self.assertIn('autocomplete="current-password"', source)
