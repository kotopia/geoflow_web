from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from django.test import RequestFactory, SimpleTestCase

from geoflow_ops.process_workflow import default_stage_for_event, normalize_stage
from geoflow_ops.services.entity_access import SCOPE_PERMISSIONS
from geoflow_ops.views_events import _derive_lineage, delete_event


ROOT = Path(__file__).resolve().parent


class Phase4EventWorkflowVocabularyTests(SimpleTestCase):
    def test_known_legacy_stage_aliases_are_normalized(self):
        self.assertEqual(normalize_stage("project"), "execution")
        self.assertEqual(normalize_stage("blilling"), "settlement")

    def test_unknown_legacy_stage_is_preserved(self):
        self.assertEqual(normalize_stage("customer_custom_stage"), "customer_custom_stage")

    def test_new_event_types_have_expected_default_stages(self):
        self.assertEqual(default_stage_for_event("kickoff_doc"), "kickoff")
        self.assertEqual(default_stage_for_event("completion_inspection"), "closeout")
        self.assertEqual(default_stage_for_event("final_payment"), "settlement")

    def test_project_scope_uses_project_permission_vocabulary(self):
        self.assertEqual(SCOPE_PERMISSIONS["project"]["read"], "projects.view")
        self.assertEqual(SCOPE_PERMISSIONS["project"]["write"], "projects.edit")


class Phase4EventLineageTests(SimpleTestCase):
    @patch("geoflow_ops.views_events.Project")
    def test_project_event_derives_contract_and_project_lineage(self, project_model):
        project_id = uuid4()
        contract_id = uuid4()
        project_model.objects.using.return_value.filter.return_value.only.return_value.first.return_value = (
            SimpleNamespace(id=project_id, contract_id=contract_id)
        )

        actual_contract_id, actual_project_id = _derive_lineage(
            "tenant", "project", project_id
        )

        self.assertEqual(actual_contract_id, contract_id)
        self.assertEqual(actual_project_id, project_id)

    def test_contract_event_uses_contract_scope_as_lineage(self):
        contract_id = uuid4()
        actual_contract_id, actual_project_id = _derive_lineage(
            "tenant", "contract", contract_id
        )
        self.assertEqual(actual_contract_id, contract_id)
        self.assertIsNone(actual_project_id)


class Phase4EventHistoryTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @patch("geoflow_ops.views_events.get_event_for_access")
    @patch("geoflow_ops.views_events.require_tenant_context", return_value="tenant")
    def test_delete_endpoint_voids_event_instead_of_deleting_it(
        self, require_tenant_context_mock, get_event_mock
    ):
        event = SimpleNamespace(
            id=uuid4(),
            payload={},
            status="open",
            save=Mock(),
            delete=Mock(),
        )
        get_event_mock.return_value = event
        request = self.factory.post("/events/delete/")
        request.user = SimpleNamespace(is_authenticated=True, username="worker@example.com", email="")
        request.session = {"tenant_db_alias": "tenant"}

        response = delete_event(request, event.id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(event.status, "void")
        self.assertIn("voided_at", event.payload)
        self.assertEqual(event.payload["voided_by"], "worker@example.com")
        event.save.assert_called_once()
        event.delete.assert_not_called()


class Phase4EventMigrationContractTests(SimpleTestCase):
    def test_migration_preserves_contract_one_to_many_project_shape(self):
        source = (
            ROOT / "migrations" / "0019_phase4_event_workflow_foundation.py"
        ).read_text(encoding="utf-8")
        self.assertIn("ADD COLUMN IF NOT EXISTS contract_id uuid NULL", source)
        self.assertNotIn("UNIQUE (contract_id)", source)
        self.assertNotIn("UNIQUE(contract_id)", source)

    def test_migration_backfills_lineage_and_only_known_legacy_stage_tokens(self):
        source = (
            ROOT / "migrations" / "0019_phase4_event_workflow_foundation.py"
        ).read_text(encoding="utf-8")
        self.assertIn("SET contract_id = scope_id", source)
        self.assertIn("SET project_id = scope_id", source)
        self.assertIn("FROM prj.projects AS p", source)
        self.assertIn("WHERE stage = 'project'", source)
        self.assertIn("WHERE stage = 'blilling'", source)
        self.assertIn("Unknown/custom historical values are intentionally left untouched", source)
