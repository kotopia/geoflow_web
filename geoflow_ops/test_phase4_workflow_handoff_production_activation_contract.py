from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "phase4-workflow-handoff-production-activation.yml"
MIGRATION = ROOT / "geoflow_ops" / "migrations" / "0024_phase4_workflow_handoff_and_contract_access.py"


class WorkflowHandoffProductionActivationContractTests(SimpleTestCase):
    def test_activation_is_release_and_production_environment_guarded(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("release/stabilized-deploy", source)
        self.assertIn("environment: production", source)
        self.assertIn("github.sha", source)
        self.assertIn("workflow_handoff_activation_exact_release=yes", source)
        self.assertIn("candidate_sha_not_current_release_head", source)

    def test_activation_targets_only_stabilized_service(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("service='geoflow-stabilized.service'", source)
        self.assertNotIn("iroomsng", source.lower())
        self.assertNotIn("nginx", source.lower())

    def test_activation_verifies_existing_business_rows_and_event_digest(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        for token in (
            '"contracts": int(scalar(cur, "SELECT COUNT(*) FROM ctr.contracts"))',
            '"projects": int(scalar(cur, "SELECT COUNT(*) FROM prj.projects"))',
            '"scope_items": int(scalar(cur, "SELECT COUNT(*) FROM prj.scope_item"))',
            '"employees": int(scalar(cur, "SELECT COUNT(*) FROM hr.employee_profile"))',
            '"attachments": int(scalar(cur, "SELECT COUNT(*) FROM ops.attachments"))',
            '"events": int(scalar(cur, "SELECT COUNT(*) FROM ops.process_events"))',
            "event_digest_before",
            "existing event content changed",
        ):
            self.assertIn(token, source)

    def test_activation_allows_only_expected_department_seed_delta(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("missing_departments", source)
        self.assertIn("department seed delta unexpected", source)
        self.assertIn("already-applied department count changed", source)
        self.assertIn("migration created contract access requests", source)

    def test_activation_deploys_exact_release_and_checks_public_login(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("pip check", source)
        self.assertIn("manage.py\" check", source)
        self.assertIn("collectstatic --noinput", source)
        self.assertIn("systemctl restart \"$service\"", source)
        self.assertIn("https://geoflow.co.kr/login/", source)
        self.assertIn("workflow_handoff_production_activation_complete=yes", source)
        self.assertIn("workflow_handoff_activation_code_rollback_started=yes", source)

    def test_migration_is_additive_and_does_not_precreate_access_requests(self):
        source = MIGRATION.read_text(encoding="utf-8").lower()
        self.assertIn("create table if not exists ops.contract_document_access_requests", source)
        self.assertIn("insert into hr.departments", source)
        self.assertNotIn("insert into ops.contract_document_access_requests", source)
        for forbidden in (
            "delete from ctr.contracts",
            "delete from prj.projects",
            "delete from prj.scope_item",
            "delete from hr.employee_profile",
            "delete from ops.process_events",
            "truncate ",
        ):
            self.assertNotIn(forbidden, source)
