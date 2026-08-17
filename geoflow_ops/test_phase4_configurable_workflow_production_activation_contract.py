from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "phase4-configurable-workflow-production-activation.yml"


class Phase4ConfigurableWorkflowProductionActivationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.source = WORKFLOW.read_text(encoding="utf-8")
        cls.lowered = cls.source.lower()

    def test_activation_is_protected_and_exact_release_bound(self):
        self.assertIn("environment: production", self.source)
        self.assertIn('test "$(git rev-parse HEAD)" = "$GITHUB_SHA"', self.source)
        self.assertIn("configurable_workflow_activation_blocker=release_advanced", self.source)
        self.assertIn("candidate_sha_not_current_release_head", self.source)
        self.assertIn("git -C \"$repo\" cat-file -e \"$candidate_sha:$migration_path\"", self.source)

    def test_only_stabilized_service_and_geoflow_health_are_targeted(self):
        self.assertIn("service='geoflow-stabilized.service'", self.source)
        self.assertNotIn("iroomsng", self.lowered)
        self.assertIn("https://geoflow.co.kr/login/", self.source)
        self.assertIn("configurable_workflow_activation_public_login_status", self.source)

    def test_dynamic_tenants_and_dependency_are_fail_closed(self):
        self.assertIn("GroupDBConfig", self.source)
        self.assertIn("resolve_tenant_db_password", self.source)
        self.assertIn('DEPENDENCY = "0022_phase4_project_participation_scope"', self.source)
        self.assertIn('MIGRATION = "0023_phase4_configurable_workflow_foundation"', self.source)
        self.assertIn("schema_absent_skipped", self.source)
        self.assertIn("partial tenant configurable-workflow schema cannot be skipped", self.source)
        self.assertIn("not_all_active_tenants_accounted", self.source)

    def test_business_rows_and_events_are_preserved(self):
        for key in (
            '"contracts": int(scalar(cur, "SELECT COUNT(*) FROM ctr.contracts"))',
            '"projects": int(scalar(cur, "SELECT COUNT(*) FROM prj.projects"))',
            '"members": int(scalar(cur, "SELECT COUNT(*) FROM prj.project_members"))',
            '"employees": int(scalar(cur, "SELECT COUNT(*) FROM hr.employee_profile"))',
            '"attachments": int(scalar(cur, "SELECT COUNT(*) FROM ops.attachments"))',
            '"events": int(scalar(cur, "SELECT COUNT(*) FROM ops.process_events"))',
        ):
            self.assertIn(key, self.source)
        self.assertIn("event_digest_after != event_digest_before", self.source)
        self.assertIn("existing event content changed", self.source)
        for destructive in (
            "delete from ctr.contracts",
            "truncate ctr.contracts",
            "drop table ctr.contracts",
            "delete from ops.process_events",
            "truncate ops.process_events",
            "drop table ops.process_events",
            "delete from prj.projects",
            "delete from hr.employee_profile",
            "delete from ops.attachments",
            "delete from prj.project_members",
        ):
            self.assertIn(destructive, self.lowered)
        self.assertIn("destructive_candidate_migration", self.source)

    def test_status_normalization_is_verified_as_exact_distribution(self):
        self.assertIn("STATUS_ALIASES", self.source)
        self.assertIn("expected_status_counts", self.source)
        self.assertIn("statuses_after != expected_statuses", self.source)
        self.assertIn("contract status normalization exceeded reviewed aliases", self.source)
        self.assertIn("reviewed contract status aliases remain", self.source)

    def test_settings_and_day_worker_are_verified(self):
        for system_key in (
            "contract.status", "contract.kind", "event.stage", "event.type", "event.status",
            "event.type.pre_contract", "event.type.contract", "event.type.kickoff",
            "event.type.execution", "event.type.inspection", "event.type.closeout",
            "event.type.billing",
        ):
            self.assertIn(system_key, self.source)
        self.assertIn("required settings system keys missing", self.source)
        self.assertIn("day-worker employment type missing", self.source)
        self.assertIn("configurable_workflow_activation_db_complete=yes", self.source)
        self.assertIn("configurable_workflow_production_activation_complete=yes", self.source)

    def test_candidate_migration_sql_is_loaded_from_exact_sha(self):
        self.assertIn('subprocess.check_output(', self.source)
        self.assertIn('["git", "-C", repo, "show", f"{candidate_sha}:{migration_path}"]', self.source)
        self.assertIn("module.Migration.operations", self.source)
        self.assertIn("cur.execute(migration_sql)", self.source)


if __name__ == "__main__":
    unittest.main()
