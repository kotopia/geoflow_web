from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "cheonan-tenant-readiness-diagnostic.yml"


class CheonanTenantReadinessContractTests(TestCase):
    def _text(self) -> str:
        return WORKFLOW.read_text(encoding="utf-8")

    def test_diagnostic_is_production_gated_and_release_scoped(self):
        text = self._text()
        self.assertIn("environment: production", text)
        self.assertIn("release/stabilized-deploy", text)
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("cheonan_db", text)

    def test_diagnostic_is_read_only(self):
        text = self._text()
        for forbidden in (
            "UPDATE groups",
            "UPDATE user_group_map",
            "UPDATE group_db_config",
            "INSERT INTO",
            "DELETE FROM",
            "systemctl restart",
            "systemctl stop",
            "systemctl start",
            "git reset",
            "git checkout",
            "git pull",
            "put_secret_value",
            "update_secret",
            "create_secret",
        ):
            self.assertNotIn(forbidden, text)

    def test_diagnostic_never_prints_connection_values_or_secrets(self):
        text = self._text()
        for forbidden in (
            "print(stored_password",
            "print(resolved_stored",
            "print(secret_password",
            "print(db_host",
            "print(db_user",
            "print(db_name",
            "print(static_password",
            "cat .env",
            "printenv",
            "set -x",
        ):
            self.assertNotIn(forbidden, text)
        self.assertIn("cheonan_diag_password_mode=", text)
        self.assertIn("cheonan_diag_secret_matches_stored=", text)
        self.assertIn("cheonan_diag_password_matches_static=", text)

    def test_diagnostic_checks_authorization_metadata_and_connectivity(self):
        text = self._text()
        for expected in (
            "cheonan_diag_group_dropdown_eligible=",
            "cheonan_diag_memberships_exact_active=",
            "cheonan_diag_active_verified_memberships=",
            "cheonan_diag_permissionless_active_roles=",
            "cheonan_diag_group_config_connects=",
            "cheonan_diag_static_alias_connects=",
            "cheonan_diag_secret_connects=",
        ):
            self.assertIn(expected, text)


if __name__ == "__main__":
    unittest.main()
