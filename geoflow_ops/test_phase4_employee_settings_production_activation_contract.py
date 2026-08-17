from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "phase4-employee-settings-production-activation.yml"


class Phase4EmployeeSettingsProductionActivationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.source = WORKFLOW.read_text(encoding="utf-8")
        cls.lowered = cls.source.lower()

    def test_production_activation_is_protected_and_exact_release_bound(self):
        self.assertIn("environment: production", self.source)
        self.assertIn('test "$(git rev-parse HEAD)" = "$GITHUB_SHA"', self.source)
        self.assertIn("employee_settings_activation_blocker=release_advanced", self.source)
        self.assertIn("candidate_sha_not_current_release_head", self.source)

    def test_only_stabilized_service_is_targeted(self):
        self.assertIn("service='geoflow-stabilized.service'", self.source)
        self.assertNotIn("iroomsng", self.lowered)
        self.assertIn("https://geoflow.co.kr/login/", self.source)
        self.assertIn("employee_settings_activation_public_login_status", self.source)

    def test_activation_uses_dynamic_active_tenants_and_0020_dependency(self):
        self.assertIn("GroupDBConfig", self.source)
        self.assertIn("resolve_tenant_db_password", self.source)
        self.assertIn('DEPENDENCY = "0020_phase4_project_task_execution"', self.source)
        self.assertIn('MIGRATION = "0021_phase4_employee_settings_foundation"', self.source)
        self.assertIn("schema_absent_skipped", self.source)

    def test_employee_and_attachment_rows_are_preserved(self):
        self.assertIn("employee_before", self.source)
        self.assertIn("employee_after", self.source)
        self.assertIn("employee profile row count changed", self.source)
        self.assertIn("attachments_before", self.source)
        self.assertIn("attachments_after", self.source)
        self.assertIn("attachment row count changed", self.source)
        for token in (
            "delete from hr.employee_profile",
            "truncate hr.employee_profile",
            "drop table hr.employee_profile",
            "delete from ops.attachments",
            "truncate ops.attachments",
            "drop table ops.attachments",
        ):
            self.assertNotIn(token, self.lowered)

    def test_required_settings_and_history_tables_are_verified(self):
        for relation in (
            "ops.settings_nodes",
            "hr.employee_education",
            "hr.employee_qualification",
            "hr.employee_technical_grade",
            "hr.employee_career",
        ):
            self.assertIn(relation, self.source)
        for root in ("domain.hr", "domain.contract", "domain.project", "domain.event", "domain.gis"):
            self.assertIn(root, self.source)
        self.assertIn("employee_settings_activation_db_complete=yes", self.source)
        self.assertIn("employee_settings_production_activation_complete=yes", self.source)


if __name__ == "__main__":
    unittest.main()
