from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "phase4-task-dashboard-production-activation.yml"


class Phase4TaskDashboardProductionActivationContractTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.source = WORKFLOW.read_text(encoding="utf-8")
        cls.lowered = cls.source.lower()

    def test_activation_is_production_protected_and_exact_release_bound(self):
        self.assertIn("environment: production", self.source)
        self.assertIn('test "$(git rev-parse HEAD)" = "$GITHUB_SHA"', self.source)
        self.assertIn("task_dashboard_activation_blocker=release_advanced", self.source)
        self.assertIn("candidate_sha_not_current_release_head", self.source)

    def test_activation_targets_only_stabilized_service(self):
        self.assertIn("service='geoflow-stabilized.service'", self.source)
        self.assertNotIn("iroomsng", self.lowered)
        self.assertIn("https://geoflow.co.kr/login/", self.source)

    def test_activation_uses_dynamic_active_tenants(self):
        self.assertIn("GroupDBConfig", self.source)
        self.assertIn("resolve_tenant_db_password", self.source)
        self.assertNotIn("cheonan_db", self.source)
        self.assertIn('MIGRATION = "0020_phase4_project_task_execution"', self.source)
        self.assertIn('DEPENDENCY = "0019_phase4_event_workflow_foundation"', self.source)

    def test_activation_is_additive_and_never_deletes_scope_rows(self):
        for token in (
            "delete from prj.scope_item",
            "truncate prj.scope_item",
            "drop table prj.scope_item",
        ):
            self.assertNotIn(token, self.lowered)
        self.assertIn("scope item row count changed", self.source)
        self.assertIn("conn.rollback()", self.source)
        self.assertIn("conn.commit()", self.source)

    def test_activation_adds_only_reviewed_task_columns(self):
        for token in (
            "ADD COLUMN IF NOT EXISTS progress_qty",
            "ADD COLUMN IF NOT EXISTS status",
            "ADD COLUMN IF NOT EXISTS completed_at",
            "ADD COLUMN IF NOT EXISTS assignee_employee_id",
            "ADD COLUMN IF NOT EXISTS variance_reason",
        ):
            self.assertIn(token, self.source)
        self.assertIn("nothing is auto-declared complete", self.lowered)
