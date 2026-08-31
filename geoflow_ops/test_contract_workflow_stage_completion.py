from pathlib import Path

from django.test import SimpleTestCase

from geoflow_ops.process_workflow import (
    CONTRACT_COMPLETION_EVENT_TYPE,
    CONTRACT_LIFECYCLE_STAGE_PHASES,
    EVENT_TRANSITION_TARGETS,
    LEGACY_EVENT_TRANSITION_TARGETS,
    transition_stage_for_event,
)


ROOT = Path(__file__).resolve().parent


class ContractWorkflowStageCompletionTests(SimpleTestCase):
    def test_process_stage_mapping_is_exact_six_stage_lifecycle(self):
        self.assertEqual(
            tuple(CONTRACT_LIFECYCLE_STAGE_PHASES),
            ("preparation", "contract", "kickoff", "execution", "closeout", "complete"),
        )
        for stage in CONTRACT_LIFECYCLE_STAGE_PHASES:
            self.assertEqual(CONTRACT_LIFECYCLE_STAGE_PHASES[stage], stage)
        self.assertNotIn("billing", CONTRACT_LIFECYCLE_STAGE_PHASES)
        self.assertNotIn("inspection", CONTRACT_LIFECYCLE_STAGE_PHASES)

    def test_only_reviewed_transition_events_advance_process_stage(self):
        self.assertEqual(EVENT_TRANSITION_TARGETS["contract_signed"], "contract")
        self.assertEqual(EVENT_TRANSITION_TARGETS["kickoff_submitted"], "kickoff")
        self.assertEqual(EVENT_TRANSITION_TARGETS["kickoff_approved"], "execution")
        self.assertEqual(EVENT_TRANSITION_TARGETS["closeout_submitted"], "closeout")
        self.assertEqual(EVENT_TRANSITION_TARGETS["closeout_approved"], "complete")
        for ordinary in (
            "estimate", "bid", "award", "contract_change", "contract_cancel",
            "kickoff_meeting", "progress_report", "suspend", "resume",
            "closeout_inspection",
        ):
            self.assertIsNone(transition_stage_for_event(ordinary))

    def test_workflow_state_is_transition_event_driven_and_never_stage_select_driven(self):
        source = (ROOT / "services" / "workflow_state.py").read_text(encoding="utf-8")
        runtime = source.split("def contract_workflow_summaries", 1)[1]
        self.assertIn("target_stage = transition_stage_for_event(event_type)", runtime)
        self.assertIn("highest reached transition wins", source)
        self.assertIn("Finance, custom and ordinary non-transition events", runtime)
        self.assertNotIn("phase = CONTRACT_LIFECYCLE_STAGE_PHASES.get(stage)", runtime)

    def test_completion_is_the_closeout_approval_event(self):
        self.assertEqual(CONTRACT_COMPLETION_EVENT_TYPE, "closeout_approved")
        self.assertEqual(transition_stage_for_event("closeout_approved"), "complete")
        # Migrated production history remains recognized without rewriting rows.
        self.assertEqual(LEGACY_EVENT_TRANSITION_TARGETS["closeout_complete"], "complete")

    def test_generic_event_options_include_canonical_transition_events(self):
        service = (ROOT / "services" / "tenant_settings.py").read_text(encoding="utf-8")
        self.assertIn("Canonical transition", service)
        self.assertNotIn("code != CONTRACT_COMPLETION_EVENT_TYPE", service)
        self.assertIn("code not in DEPRECATED_EVENT_TYPE_CODES", service)

    def test_legacy_contract_completion_client_is_normalized_on_write(self):
        workflow = (ROOT / "process_workflow.py").read_text(encoding="utf-8")
        security = (ROOT / "event_security_views.py").read_text(encoding="utf-8")
        detail = (ROOT / "templates" / "geoflow_ops" / "contracts" / "contract_detail.html").read_text(encoding="utf-8")
        self.assertIn('LEGACY_CONTRACT_COMPLETION_EVENT_TYPE = "closeout_complete"', workflow)
        self.assertIn("normalize_event_type_for_write", security)
        self.assertIn("_replace_request_json_body", security)
        # The pre-existing dedicated button remains backward-compatible while
        # persistence is normalized to the canonical 준공승인 event.
        self.assertIn('id="btn-contract-complete"', detail)
        self.assertIn("event_type: 'closeout_complete'", detail)

    def test_legacy_completed_status_is_converted_then_preserved_as_history(self):
        migration = (ROOT / "migrations" / "0026_contract_completion_event_backfill.py").read_text(encoding="utf-8")
        self.assertIn("legacy_contract_status_migration", migration)
        self.assertIn("NOT EXISTS", migration)
        self.assertIn("'closeout_complete'", migration)
        self.assertIn("SET status = NULL", migration)
        self.assertIn("occurred_at_inferred", migration)

        workflow = (ROOT / "services" / "workflow_state.py").read_text(encoding="utf-8")
        runtime = workflow.split("def contract_workflow_summaries", 1)[1]
        self.assertNotIn('getattr(contract, "status"', runtime)
        self.assertIn("DEPRECATED_EVENT_TYPE_CODES", workflow)

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
        self.assertIn("<th>업무단계</th>", listing)
        self.assertIn('data-col="workflow"', listing)
        self.assertNotIn("obj.contract.status", detail)
        self.assertIn("contract_workflow.major_label", detail)
        self.assertIn("업무단계", detail)
