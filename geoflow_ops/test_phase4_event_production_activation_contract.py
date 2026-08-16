from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "phase4-event-production-activation.yml"


class Phase4EventProductionActivationContractTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.source = WORKFLOW.read_text(encoding="utf-8")
        cls.lowered = cls.source.lower()

    def test_activation_is_production_protected_and_exact_release_bound(self):
        self.assertIn("environment: production", self.source)
        self.assertIn('test "$(git rev-parse HEAD)" = "$GITHUB_SHA"', self.source)
        self.assertIn("phase4_event_activation_blocker=release_advanced", self.source)
        self.assertIn("candidate_sha_not_current_release_head", self.source)

    def test_activation_targets_only_stabilized_service(self):
        self.assertIn("service='geoflow-stabilized.service'", self.source)
        self.assertNotIn("iroomsng", self.lowered)
        self.assertIn("http://127.0.0.1:8011/login/", self.source)
        self.assertIn("https://geoflow.co.kr/login/", self.source)

    def test_activation_preserves_contract_one_to_many_project_shape(self):
        self.assertNotIn("unique (contract_id)", self.lowered)
        self.assertNotIn("unique(contract_id)", self.lowered)
        self.assertNotIn("delete from prj.projects", self.lowered)
        self.assertNotIn("delete from ctr.contracts", self.lowered)

    def test_activation_applies_only_expected_event_migration(self):
        self.assertIn('APP = "webgisapp"', self.source)
        self.assertIn('DEPENDENCY = "0018_processevent_processeventattachment"', self.source)
        self.assertIn('MIGRATION = "0019_phase4_event_workflow_foundation"', self.source)
        self.assertIn("ALTER TABLE ops.process_events ADD COLUMN IF NOT EXISTS contract_id", self.source)
        self.assertIn("UPDATE ops.process_events SET stage = 'execution' WHERE stage = 'project'", self.source)
        self.assertIn("UPDATE ops.process_events SET stage = 'billing' WHERE stage = 'blilling'", self.source)
        self.assertIn("INSERT INTO django_migrations", self.source)

    def test_activation_never_deletes_business_rows(self):
        forbidden = (
            "delete from ops.process_events",
            "truncate ops.process_events",
            "drop table ops.process_events",
            "delete from prj.projects",
            "delete from ctr.contracts",
        )
        for token in forbidden:
            self.assertNotIn(token, self.lowered)
        self.assertIn('raise RuntimeError("event row count changed")', self.source)

    def test_activation_fails_closed_and_rolls_back(self):
        self.assertIn("conn.rollback()", self.source)
        self.assertIn("conn.commit()", self.source)
        self.assertIn("0018 dependency not applied", self.source)
        self.assertIn("legacy stage normalization incomplete", self.source)
        self.assertIn("contract lineage backfill incomplete", self.source)
        self.assertIn("phase4_event_activation_code_rollback_started=yes", self.source)

    def test_schema_absent_tenant_is_skipped_only_when_business_schema_absent(self):
        self.assertIn("partial tenant business schema cannot be skipped", self.source)
        self.assertIn('totals["schema_absent_skipped"] += 1', self.source)
