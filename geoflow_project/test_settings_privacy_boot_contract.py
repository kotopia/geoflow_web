from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent


class SettingsPrivacyBootContractTests(unittest.TestCase):
    def test_retired_rrn_key_is_not_required_at_boot(self):
        source = (ROOT / "settings.py").read_text(encoding="utf-8")
        self.assertNotIn('get_env_required("RRN_SYM_KEY")', source)
        self.assertNotIn("RRN_SYM_KEY =", source)

    def test_provisioning_failure_does_not_reference_undefined_dotenv_state(self):
        source = (ROOT / "settings.py").read_text(encoding="utf-8")
        self.assertNotIn("_loaded", source)
        self.assertIn(
            '"Tenant provisioning is ENABLED but missing env vars: "',
            source,
        )


if __name__ == "__main__":
    unittest.main()
