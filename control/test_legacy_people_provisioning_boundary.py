from pathlib import Path
from unittest import TestCase


CONTROL_DIR = Path(__file__).resolve().parent


class LegacyPeopleProvisioningBoundaryTests(TestCase):
    def test_legacy_people_helper_defaults_to_inactive_placeholder(self):
        source = (CONTROL_DIR / "services_people.py").read_text(encoding="utf-8")

        self.assertIn("is_active: bool = False", source)
        self.assertIn("is_staff: bool = False", source)
        self.assertIn("VALUES (gen_random_uuid(), %s, FALSE, FALSE, FALSE", source)

    def test_legacy_people_helper_rejects_activation_request(self):
        source = (CONTROL_DIR / "services_people.py").read_text(encoding="utf-8")

        self.assertIn("if is_active or is_staff:", source)
        self.assertIn("Legacy people provisioning cannot activate central accounts", source)


if __name__ == "__main__":
    unittest.main()
