from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "phase4-event-handoff-production-activation.yml"


class EventHandoffProductionActivationContractTests(SimpleTestCase):
    def test_activation_is_production_protected_and_exact_release_bound(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("environment: production", source)
        self.assertIn("release/stabilized-deploy", source)
        self.assertIn("test \"$(git rev-parse HEAD)\" = \"$GITHUB_SHA\"", source)
        self.assertIn("candidate_sha_not_current_release_head", source)
        self.assertIn("0024_phase4_event_handoff_and_contract_access.py", source)
        self.assertIn("0023_phase4_configurable_workflow_foundation", source)

    def test_activation_preserves_business_rows_and_limits_seed_changes(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("existing department row changed", source)
        self.assertIn("department seed count exceeded reviewed additions", source)
        self.assertIn("existing event content changed", source)
        self.assertIn("contract status distribution changed", source)
        self.assertIn("contract document access rows changed during migration", source)
        self.assertIn("required department seed missing", source)
        self.assertIn("event_handoff_activation_db_complete=yes", source)
        self.assertIn("not_all_active_tenants_accounted", source)

    def test_activation_deploys_only_stabilized_service_with_health_and_rollback(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("service='geoflow-stabilized.service'", source)
        self.assertNotIn("iroomsng", source.lower())
        self.assertIn("event_handoff_activation_code_rollback_started=yes", source)
        self.assertIn("systemctl restart \"$service\"", source)
        self.assertIn("event_handoff_activation_public_login_status", source)
        self.assertIn("event_handoff_production_activation_complete=yes", source)

    def test_activation_scans_destructive_sql_and_does_not_mutate_infrastructure(self):
        source = WORKFLOW.read_text(encoding="utf-8").lower()
        self.assertIn("destructive_candidate_migration", source)
        self.assertIn("delete from ctr.contracts", source)
        self.assertIn("truncate ops.process_events", source)
        self.assertNotIn("aws iam", source)
        self.assertNotIn("aws secretsmanager put", source)
        self.assertNotIn("aws s3 rm", source)
