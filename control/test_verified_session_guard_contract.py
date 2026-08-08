from pathlib import Path
from unittest import TestCase


CONTROL_DIR = Path(__file__).resolve().parent


class VerifiedSessionGuardContractTests(TestCase):
    def test_central_session_guard_requires_verified_account(self):
        source = (CONTROL_DIR / "middleware.py").read_text(encoding="utf-8")

        self.assertIn("SELECT TRUE", source)
        self.assertIn("AND is_active = TRUE", source)
        self.assertIn("AND email_verified = TRUE", source)

    def test_tenant_freshness_requires_verified_central_account(self):
        source = (CONTROL_DIR / "middleware.py").read_text(encoding="utf-8")

        self.assertIn("AND u.is_active = TRUE", source)
        self.assertIn("AND u.email_verified = TRUE", source)


if __name__ == "__main__":
    unittest.main()
