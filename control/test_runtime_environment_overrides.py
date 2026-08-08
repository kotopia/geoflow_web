from pathlib import Path
from unittest import TestCase


CONTROL_DIR = Path(__file__).resolve().parent


class RuntimeEnvironmentOverrideContractTests(TestCase):
    def test_control_app_applies_runtime_mail_and_origin_overrides(self):
        source = (CONTROL_DIR / "apps.py").read_text(encoding="utf-8")

        self.assertIn('os.environ.get("DEFAULT_FROM_EMAIL")', source)
        self.assertIn('settings.DEFAULT_FROM_EMAIL = default_from_email', source)
        self.assertIn('os.environ.get("SITE_ORIGIN")', source)
        self.assertIn('settings.SITE_ORIGIN = site_origin.rstrip("/")', source)
        self.assertIn("def ready(self)", source)
        self.assertNotIn("logger.", source)

    def test_legacy_mail_services_prefer_runtime_environment(self):
        invite_source = (CONTROL_DIR / "services_mail.py").read_text(encoding="utf-8")
        password_source = (
            CONTROL_DIR / "services" / "emailer.py"
        ).read_text(encoding="utf-8")

        self.assertIn('os.environ.get("SITE_ORIGIN")', invite_source)
        self.assertIn('os.environ.get("DEFAULT_FROM_EMAIL")', invite_source)
        self.assertIn('os.environ.get("DEFAULT_FROM_EMAIL")', password_source)
        self.assertNotIn("EMAIL_HOST_PASSWORD", invite_source)
        self.assertNotIn("EMAIL_HOST_PASSWORD", password_source)
