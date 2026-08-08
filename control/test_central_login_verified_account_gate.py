from pathlib import Path
from unittest import TestCase


CONTROL_DIR = Path(__file__).resolve().parent


class CentralLoginVerifiedAccountGateTests(TestCase):
    def test_login_query_requires_active_and_verified_account(self):
        source = (CONTROL_DIR / "views_auth.py").read_text(encoding="utf-8")

        self.assertIn("AND is_active = TRUE", source)
        self.assertIn("AND email_verified = TRUE", source)
        self.assertIn("burn_central_login_password_check(pw)", source)
        self.assertIn('{"error": PUBLIC_LOGIN_ERROR}', source)


if __name__ == "__main__":
    unittest.main()
