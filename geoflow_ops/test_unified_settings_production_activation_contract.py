from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class UnifiedSettingsProductionActivationContractTests(unittest.TestCase):
    def setUp(self):
        self.source = (
            ROOT / ".github" / "workflows" / "unified-settings-production-activation.yml"
        ).read_text(encoding="utf-8")

    def test_activation_is_release_and_production_gated(self):
        self.assertIn("release/stabilized-deploy", self.source)
        self.assertIn("environment: production", self.source)
        self.assertIn("candidate_sha_not_current_release_head", self.source)
        self.assertIn("StrictHostKeyChecking=yes", self.source)

    def test_activation_targets_only_reviewed_migration(self):
        self.assertIn("0028_move_due_at_to_event_end_at", self.source)
        self.assertIn("0029_unified_settings_registry", self.source)
        self.assertIn("candidate_migration_missing", self.source)
        self.assertIn("unexpected_migration_shape", self.source)
        self.assertIn("pg_advisory_xact_lock", self.source)

    def test_every_active_tenant_is_accounted_for(self):
        self.assertIn("active_tenants", self.source)
        self.assertIn("secret_resolution_failed", self.source)
        self.assertIn("connection_failed", self.source)
        self.assertIn("migration_failed", self.source)
        self.assertIn("not_all_active_tenants_accounted", self.source)

    def test_business_rows_and_registry_shape_are_verified(self):
        for table in (
            "ctr.contracts",
            "prj.projects",
            "prj.project_members",
            "hr.employee_profile",
            "ops.attachments",
            "ops.process_events",
        ):
            self.assertIn(table, self.source)
        self.assertIn("row count changed", self.source)
        self.assertIn("REQUIRED_FIELD_REFS", self.source)
        self.assertIn("Process Stage is not the reviewed six-stage set", self.source)
        self.assertIn("settlement event types are incomplete", self.source)
        self.assertIn("superseded HR master tables remain", self.source)

    def test_deploy_has_health_check_and_code_rollback(self):
        self.assertIn("rollback_code", self.source)
        self.assertIn("systemctl restart", self.source)
        self.assertIn("public_login_not_200_after_activation", self.source)


if __name__ == "__main__":
    unittest.main()
