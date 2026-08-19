from pathlib import Path

from django.test import SimpleTestCase

from geoflow_ops.process_workflow import default_stage_for_event
from geoflow_ops.services.tenant_settings import settings_options
from geoflow_ops.services.workflow_state import (
    _stage_summary,
    fallback_stage_for_contract_status,
    major_phase_for_stage,
)


ROOT = Path(__file__).resolve().parent


class ContractWorkboardCompatibilityTests(SimpleTestCase):
    def _client_source(self):
        return (
            ROOT / "static" / "geoflow_ops" / "js" / "process-workboard-ui.js"
        ).read_text(encoding="utf-8")

    def test_contract_timeline_client_consumes_cross_department_fields(self):
        source = self._client_source()
        self.assertIn("assignmentOptionsUrl", source)
        self.assertIn("ev.can_write", source)
        self.assertIn("ev.owner_department_name", source)
        self.assertIn("ev.assignee_employee_name", source)
        self.assertIn("ev.project_name", source)
        self.assertIn("ev.due_at", source)

    def test_contract_timeline_sends_assignment_only_when_authorized(self):
        source = self._client_source()
        self.assertIn("if (config.canAssign)", source)
        self.assertIn("payload.owner_department_id", source)
        self.assertIn("payload.assignee_employee_id", source)
        self.assertIn("due_at: fDue", source)
        self.assertIn("currentCanWrite", source)

    def test_contract_timeline_preserves_event_scope_for_merged_project_events(self):
        source = self._client_source()
        self.assertIn("currentEvent.scope_type", source)
        self.assertIn("currentEvent.scope_id", source)
        self.assertIn("currentEvent = ev", source)

    def test_contract_timeline_uses_void_language_not_physical_delete_language(self):
        source = self._client_source()
        self.assertIn("취소 처리", source)
        self.assertIn("이력은 삭제되지 않습니다", source)
        self.assertNotIn("정말 이 이벤트를 삭제하시겠습니까", source)

    def test_contract_timeline_uses_configurable_stage_type_workflow(self):
        source = self._client_source()
        self.assertIn("workflowOptionsUrl", source)
        self.assertIn("types_by_stage", source)
        self.assertIn("function populateEventTypes", source)
        self.assertIn("fStage.onchange", source)

    def test_contract_detail_uses_shared_configurable_event_endpoint(self):
        template = (
            ROOT / "templates" / "geoflow_ops" / "contracts" / "contract_detail.html"
        ).read_text(encoding="utf-8")
        urls = (ROOT / "urls.py").read_text(encoding="utf-8")
        security = (ROOT / "event_security_views.py").read_text(encoding="utf-8")

        self.assertIn("tenant:event_list", template)
        self.assertIn("tenant:event_workflow_options", template)
        self.assertIn("process-workboard-ui.js", template)
        self.assertIn("ProcessWorkboardUI.init", template)
        self.assertNotIn("process-events-ui.js", template)
        self.assertIn("event_security_views.event_list", urls)
        self.assertIn("event_security_views.workflow_options", urls)
        self.assertIn("views_workboard.workboard_event_list", security)

    def test_eventless_contract_display_starts_in_contract_without_repurposing_legacy_fallback(self):
        # Established fallback semantics remain available to old callers.
        self.assertEqual(fallback_stage_for_contract_status("planned"), "pre_contract")
        self.assertEqual(fallback_stage_for_contract_status("active"), "execution")
        self.assertEqual(fallback_stage_for_contract_status("complete"), "closeout")
        # The event-driven list explicitly uses the contract stage when no event exists.
        summary = _stage_summary("contract", contract_status="active")
        self.assertEqual(summary["major_code"], "contract")
        self.assertEqual(summary["major_label"], "계약")
        self.assertEqual(summary["filter_status"], "planned")
        source = (ROOT / "services" / "workflow_state.py").read_text(encoding="utf-8")
        self.assertIn('latest.get(contract_id, (0, "contract"))', source)

    def test_kickoff_execution_and_inspection_display_as_progress(self):
        for stage in ("kickoff", "execution", "inspection"):
            # Legacy grouping label is preserved, while the UI summary is normalized.
            self.assertEqual(major_phase_for_stage(stage), ("execution", "수행(진행)"))
            summary = _stage_summary(stage)
            self.assertEqual(summary["major_label"], "진행")
            self.assertEqual(summary["filter_status"], "active")

    def test_closeout_is_separate_from_final_completion_visual(self):
        in_closeout = _stage_summary("closeout", is_complete=False)
        completed = _stage_summary("closeout", is_complete=True)
        self.assertEqual(in_closeout["major_label"], "준공")
        self.assertEqual(in_closeout["filter_status"], "complete")
        self.assertEqual(in_closeout["stage_label"], "준공")
        self.assertFalse(in_closeout["is_complete"])
        self.assertEqual(completed["stage_label"], "준공 완료")
        self.assertTrue(completed["is_complete"])
        self.assertNotEqual(in_closeout["phase_class"], completed["phase_class"])

    def test_closeout_completion_is_explicit_and_available_to_legacy_configured_tenants(self):
        self.assertEqual(default_stage_for_event("closeout_complete"), "closeout")
        closeout_options = dict(settings_options(None, "event.type.closeout"))
        self.assertEqual(closeout_options.get("closeout_complete"), "준공완료")
        source = (ROOT / "services" / "workflow_state.py").read_text(encoding="utf-8")
        self.assertIn('_CLOSEOUT_COMPLETE_EVENT_TYPES = {"closeout_complete"}', source)
        self.assertIn("delivery alone is not final closure", source)

    def test_billing_is_not_a_business_phase(self):
        source = (ROOT / "services" / "workflow_state.py").read_text(encoding="utf-8")
        stage_order = source.split("_STAGE_ORDER = {", 1)[1].split("}", 1)[0]
        self.assertNotIn('"billing"', stage_order)
        self.assertIn("Billing/settlement events are deliberately ignored", source)

    def test_contract_list_uses_workflow_visual_and_filter_state(self):
        template = (
            ROOT / "templates" / "geoflow_ops" / "contracts" / "contract_list.html"
        ).read_text(encoding="utf-8")
        self.assertIn("wf.phase_class", template)
        self.assertIn("wf.is_complete", template)
        self.assertIn("data-workflow-phase", template)
        self.assertIn('data-status="{{ wf.filter_status }}"', template)
        self.assertIn("gf-contract-complete", template)
        self.assertIn("{planned: '계약', active: '진행', complete: '준공'}", template)

    def test_contract_status_field_is_read_only_but_tenant_vocabulary_remains(self):
        forms = (ROOT / "forms.py").read_text(encoding="utf-8")
        self.assertIn('settings_options(alias, "contract.status")', forms)
        self.assertIn("disabled=True", forms)
        self.assertIn("업무단계는 이벤트에서 자동 변경됩니다.", forms)
