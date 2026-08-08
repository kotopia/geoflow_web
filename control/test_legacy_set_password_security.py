from pathlib import Path
from unittest import TestCase


CONTROL_DIR = Path(__file__).resolve().parent


class LegacySetPasswordSecurityContractTests(TestCase):
    def test_legacy_password_setup_uses_standard_validators_and_bounds(self):
        source = (CONTROL_DIR / "views_users_admin.py").read_text(encoding="utf-8")

        self.assertIn("validate_password(pw1, user=validator_user)", source)
        self.assertIn("MAX_LEGACY_PASSWORD_LENGTH = 128", source)
        self.assertIn("len(pw1) > MAX_LEGACY_PASSWORD_LENGTH", source)
        self.assertNotIn("if len(pw1) < 8 or pw1 != pw2", source)

    def test_password_post_values_are_marked_sensitive(self):
        source = (CONTROL_DIR / "views_users_admin.py").read_text(encoding="utf-8")

        self.assertIn('@sensitive_post_parameters("password", "password2")', source)
        self.assertIn('@sensitive_variables("email", "pw1", "pw2", "hashed")', source)
        self.assertIn('@require_http_methods(["GET", "POST"])', source)
        self.assertIn("@never_cache", source)


if __name__ == "__main__":
    unittest.main()
