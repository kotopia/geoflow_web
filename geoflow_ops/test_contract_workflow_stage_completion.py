from pathlib import Path

from django.test import SimpleTestCase

from geoflow_ops.process_workflow import (
    CONTRACT_COMPLETION_EVENT_TYPE,
    CONTRACT_LIFECYCLE_STAGE_PHASES,
)


ROOT = Path(__file__).resolve().parent


class ContractWorkflowStageCompletionTests(SimpleTestCase):
    def test_stage_mapping_drives_coarse_contract_phase(self):
        self.assertEqual(CONTRACT_LIFECYCLE_STAGE_PHASES["contract"], "contract")
        self.assertEqual(CONTRACT_LIFECYCLE_STAGE_PHASES["kickoff"], "execution")
        self.assertEqual(CONTRACT_LIFECYCLE_STAGE_PHASES["execution"], "execution")
        self.assertEqual(CONTRACT_LIFECYCLE_STAGE_PHASES["closeout"], "closeout")
        self.assertEqual(CONTRACT_LIFECYCLE_STAGE_PHASES["complete"], "complete")
        self.assertNotIn("settlement", CONTRACT_LIFECYCLE_STAGE_PHASES)

    def test_event_type_does_not_drive_progress_or_closeout(self):
        source = (ROOT / "services" / "workflow_state.py").read_text(encoding="utf-8")
        runtime = source.split("def contract_workflow_summaries", 1)[1]
        self.assertIn("phase = CONTRACT_LIFECYCLE_STAGE_PHASES.get(stage)", runtime)
        self.assertIn("highest reached non-void phase wins", source)
        # event_type is used only to recognize explicit final completion.
        self.assertIn("if event_type == CONTRACT_COMPLETION_EVENT_TYPE", runtime)

    def test_completion_requires_dedicated_server_action_after_closeout(self):
        security = (ROOT / "event_security_views.py").read_text(encoding="utf-8")
        self.assertEqual(CONTRACT_COMPLETION_EVENT_TYPE, "completion_approval")
        self.assertIn('CONTRACT_COMPLETION_ACTION_SOURCE = "contract_complete_action"', security)
        self.assertIn("def _completion_action_error", security)
        self.assertIn('stage != "closeout"', security)
        self.assertIn("reached_closeout", security)
        self.assertIn("Contract must reach closeout before completion", security)
        self.assertIn("already_complete", security)
        self.assertIn("Contract is already complete", security)

    def test_generic_event_options_hide_final_completion(self):
        service = (ROOT / "services" / "tenant_settings.py").read_text(encoding="utf-8")
        modal = (ROOT / "templates" / "geoflow_ops" / "events" / "_event_modal.html").read_text(encoding="utf-8")
        self.assertIn("option[0] != CONTRACT_COMPLETION_EVENT_TYPE", service)
        self.assertNotIn('value="completion_approval"', modal)

    def test_contract_detail_completion_button_creates_canonical_event(self):
        detail = (ROOT / "templates" / "geoflow_ops" / "contracts" / "contract_detail.html").read_text(encoding="utf-8")
        self.assertIn('id="btn-contract-complete"', detail)
        self.assertIn("event_type: 'completion_approval'", detail)
        self.assertIn("stage: 'closeout'", detail)
        self.assertIn("source: 'contract_complete_action'", detail)
        self.assertIn("완료일", detail)

    def test_legacy_completed_status_is_converted_then_cleared(self):
        migration = (ROOT / "migrations" / "0026_contract_completion_event_backfill.py").read_text(encoding="utf-8")
        self.assertIn("legacy_contract_status_migration", migration)
        self.assertIn("NOT EXISTS", migration)
        self.assertIn("'closeout_complete'", migration)
        self.assertIn("SET status = NULL", migration)
        self.assertIn("occurred_at_inferred", migration)

        workflow = (ROOT / "services" / "workflow_state.py").read_text(encoding="utf-8")
        runtime = workflow.split("def contract_workflow_summaries", 1)[1]
        dashboard = (ROOT / "views_dashboard.py").read_text(encoding="utf-8")
        terminal = dashboard.split("def _terminal_contract_ids", 1)[1].split("def _task_rows", 1)[0]
        self.assertNotIn('getattr(contract, "status"', runtime)
        self.assertNotIn("FROM ctr.contracts", terminal)
        self.assertIn("event_type IN ('completion_approval', 'contract_cancel')", terminal)

    def test_project_pages_use_linked_contract_workflow_not_contract_status(self):
        views = (ROOT / "views_projects.py").read_text(encoding="utf-8")
        listing = (ROOT / "templates" / "geoflow_ops" / "projects" / "project_list.html").read_text(encoding="utf-8")
        detail = (ROOT / "templates" / "geoflow_ops" / "projects" / "project_detail.html").read_text(encoding="utf-8")

        self.assertIn("contract_workflow_summaries", views)
        self.assertIn("contract_workflow_summary", views)
        self.assertNotIn('getattr(p.contract, "status"', views)
        self.assertNotIn('"status": obj.contract.status', views)
        self.assertIn('"contract_workflow": workflow.get("major_code")', views)
        self.assertIn('"contract_workflow_label": workflow.get("major_label")', views)

        self.assertNotIn("p.contract.status", listing)
        self.assertIn("p.contract_workflow", listing)
        self.assertIn("업무단계", listing)
        self.assertNotIn("obj.contract.status", detail)
        self.assertIn("contract_workflow.major_label", detail)
        self.assertIn("업무단계", detail)
