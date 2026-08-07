from pathlib import Path
from unittest import TestCase


CONTROL_DIR = Path(__file__).resolve().parent


class SignupActivationMailConfigContractTests(TestCase):
    def test_verification_sender_prefers_environment_override(self):
        source = (
            CONTROL_DIR / "services/signup_verification_email_delivery.py"
        ).read_text(encoding="utf-8")

        self.assertIn('os.environ.get("DEFAULT_FROM_EMAIL")', source)
        self.assertIn('getattr(', source)
        self.assertIn('"DEFAULT_FROM_EMAIL"', source)

    def test_sender_override_does_not_log_or_persist_configuration(self):
        source = (
            CONTROL_DIR / "services/signup_verification_email_delivery.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn("logger.", source)
        self.assertNotIn("cursor.execute", source)
        self.assertNotIn("password", source.lower())
