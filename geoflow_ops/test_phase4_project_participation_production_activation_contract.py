from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "phase4-project-participation-production-activation.yml"


class Phase4ProjectParticipationProductionActivationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.source = WORKFLOW.read_text(encoding="utf-8")
        cls.lowered = cls.source.lower()

    def test_production_activation_is_protected_and_exact_release_bound(self):
        self.assertIn("environment: production", self.source)
        self.assertIn('test "$(git rev-parse HEAD)" = "$GITHUB_SHA"', self.source)
        self.assertIn("project_participation_activation_blocker=release_advanced", self.source)
        self.assertIn("candidate_sha_not_current_release_head", self.source)

    def test_only_stabilized_service_is_targeted(self):
        self.assertIn("service='geoflow-stabilized.service'", self.source)
        self.assertNotIn("iroomsng", self.lowered)
        self.assertIn("https://geoflow.co.kr/login/", self.source)
        self.assertIn("project_participation_activation_public_login_status", self.source)

    def test_dynamic_active_tenants_and_dependency_are_required(self):
        self.assertIn("GroupDBConfig", self.source)
        self.assertIn("resolve_tenant_db_password", self.source)
        self.assertIn('DEPENDENCY = "0021_phase4_employee_settings_foundation"', self.source)
        self.assertIn('MIGRATION = "0022_phase4_project_participation_scope"', self.source)
        self.assertIn("schema_absent_skipped", self.source)
        self.assertIn("SET LOCAL TRANSACTION READ ONLY", self.source)

    def test_existing_business_rows_are_preserved(self):
        for before, after, message in (
            ("projects_before", "projects_after", "project row count changed"),
            ("employees_before", "employees_after", "employee row count changed"),
            ("attachments_before", "attachments_after", "attachment row count changed"),
        ):
            self.assertIn(before, self.source)
            self.assertIn(after, self.source)
            self.assertIn(message, self.source)
        for token in (
            "delete from prj.projects",
            "truncate prj.projects",
            "drop table prj.projects",
            "delete from hr.employee_profile",
            "truncate hr.employee_profile",
            "delete from ops.attachments",
            "truncate ops.attachments",
        ):
            self.assertNotIn(token, self.lowered)

    def test_project_member_integrity_is_verified(self):
        self.assertIn("prj.project_members", self.source)
        self.assertIn("ux_project_members_one_active_pm", self.source)
        self.assertIn("ux_project_members_one_active_leader", self.source)
        self.assertIn("invalid_role", self.source)
        self.assertIn("invalid_status", self.source)
        self.assertIn("duplicate_responsibility", self.source)
        self.assertIn("project_participation_activation_db_complete=yes", self.source)
        self.assertIn("project_participation_production_activation_complete=yes", self.source)

    def test_local_and_public_health_semantics_match_stabilized_runtime(self):
        self.assertIn("Host: geoflow.co.kr", self.source)
        self.assertIn("2??|3??", self.source)
        self.assertIn("[ \"$public_login\" = '200' ]", self.source)


if __name__ == "__main__":
    unittest.main()
