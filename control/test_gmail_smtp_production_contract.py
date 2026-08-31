from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


class GmailSmtpProductionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.diagnostic = (WORKFLOWS / "phase1-smtp-production-diagnostic.yml").read_text(encoding="utf-8")
        cls.sync = (WORKFLOWS / "phase1-smtp-production-sync.yml").read_text(encoding="utf-8")
        cls.activation = (WORKFLOWS / "phase1-signup-production-activation.yml").read_text(encoding="utf-8")

    def test_protected_diagnostic_authenticates_against_gmail(self):
        self.assertIn("SMTP_PROVIDER_HOST: smtp.gmail.com", self.diagnostic)
        self.assertIn("os.environ['SMTP_PROVIDER_HOST']", self.diagnostic)
        self.assertIn("server_smtp_host_is_gmail", self.diagnostic)

    def test_protected_sync_sets_complete_gmail_sender_configuration(self):
        for expected in (
            "SMTP_PROVIDER_HOST: smtp.gmail.com",
            "'USE_SMTP_EMAIL': '1'",
            "'EMAIL_HOST': 'smtp.gmail.com'",
            "'EMAIL_PORT': '587'",
            "'EMAIL_USE_TLS': 'true'",
            "'DEFAULT_FROM_EMAIL': user",
            "sender != user.lower()",
        ):
            self.assertIn(expected, self.sync)

    def test_signup_activation_keeps_gmail_as_production_provider(self):
        self.assertIn("'EMAIL_HOST': 'smtp.gmail.com'", self.activation)
        self.assertIn("'DEFAULT_FROM_EMAIL': smtp_user", self.activation)


if __name__ == "__main__":
    unittest.main()
