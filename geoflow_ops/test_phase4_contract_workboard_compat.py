from pathlib import Path

from django.test import SimpleTestCase

from geoflow_ops.process_workflow import (
    CONTRACT_COMPLETION_EVENT_TYPE,
    CONTRACT_LIFECYCLE_STAGE_PHASES,
    REQUIRED_EVENT_STAGE_CODES,
    default_stage_for_event,
)
from geoflow_ops.services.tenant_settings import event_workflow_options, settings_options
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

    def test_legacy_stage_helpers_remain_compatible_but_runtime_is_event_only(self):
        self.assertEqual(fallback_stage_for_contract_status("planned"), "pre_contract")
        self.assertEqual(fallback_stage_for_contract_status("active"), "execution")
        self.assertEqual(fallback_stage_for_contract_status("complete"), "closeout")
        self.assertEqual(major_phase_for_stage("kickoff"), ("execution", "수행(진행)"))
        source = (ROOT / "services" / "workflow_state.py").read_text(encoding="utf-8")
        runtime = source.split("def contract_workflow_summaries", 1)[1]
        self.assertNotIn('getattr(contract, "status"', runtime)
        self.assertIn("event-only", source)

    def test_contract_lifecycle_is_stage_driven(self):
        self.assertEqual(CONTRACT_LIFECYCLE_STAGE_PHASES["contract"], "contract")
        self.assertEqual(CONTRACT_LIFECYCLE_STAGE_PHASES["kickoff"], "execution")
        self.assertEqual(CONTRACT_LIFECYCLE_STAGE_PHASES["execution"], "execution")
        self.assertEqual(CONTRACT_LIFECYCLE_STAGE_PHASES["inspection"], "execution")
        self.assertEqual(CONTRACT_LIFECYCLE_STAGE_PHASES["closeout"], "closeout")
        self.assertNotIn("billing", CONTRACT_LIFECYCLE_STAGE_PHASES)
        source = (ROOT / "services" / "workflow_state.py").read_text(encoding="utf-8")
        self.assertIn("phase = CONTRACT_LIFECYCLE_STAGE_PHASES.get(stage)", source)
        self.assertIn("highest reached non-void phase wins", source)

    def test_required_event_stages_are_canonical_and_always_available(self):
        stages = dict(settings_options(None, "event.stage"))
        for code in REQUIRED_EVENT_STAGE_CODES:
            self.assertIn(code, stages)
        self.assertEqual(stages["kickoff"], "착수")
        self.assertEqual(stages["closeout"], "준공")

    def test_eventless_contract_display_is_contract(self):
        summary = _stage_summary("contract")
        self.assertEqual(summary["major_code"], "contract")
        self.assertEqual(summary["major_label"], "계약")
        self.assertEqual(summary["filter_key"], "planned")

    def test_kickoff_stage_means_progress_even_when_type_is_not_kickoff(self):
        self.assertEqual(default_stage_for_event("kickoff_doc"), "kickoff")
        summary = _stage_summary("kickoff")
        self.assertEqual(summary["major_code"], "execution")
        self.assertEqual(summary["major_label"], "진행")
        self.assertEqual(summary["filter_key"], "active")

    def test_closeout_stage_and_final_completion_are_distinct(self):
        in_closeout = _stage_summary("closeout")
        completed = _stage_summary("closeout", is_complete=True)
        self.assertEqual(in_closeout["major_code"], "closeout")
        self.assertEqual(in_closeout["major_label"], "준공")
        self.assertEqual(in_closeout["filter_key"], "pause")
        self.assertFalse(in_closeout["is_complete"])
        self.assertEqual(completed["major_code"], "complete")
        self.assertEqual(completed["major_label"], "완료")
        self.assertEqual(completed["filter_key"], "complete")
        self.assertTrue(completed["is_complete"])

    def test_legacy_completed_status_is_migrated_not_read_at_runtime(self):
        migration = (ROOT / "migrations" / "0026_contract_completion_event_backfill.py").read_text(encoding="utf-8")
        self.assertIn("legacy_contract_status_migration", migration)
        self.assertIn("'closeout_complete'", migration)
        self.assertIn("SET status = NULL", migration)
        self.assertIn("occurred_at_inferred", migration)
        workflow = (ROOT / "services" / "workflow_state.py").read_text(encoding="utf-8")
        runtime = workflow.split("def contract_workflow_summaries", 1)[1]
        self.assertNotIn('getattr(contract, "status"', runtime)
        self.assertNotIn("SELECT status FROM ctr.contracts", workflow)
        self.assertNotIn("UPDATE ctr.contracts", workflow)

    def test_completion_event_is_reserved_for_dedicated_contract_action(self):
        self.assertEqual(CONTRACT_COMPLETION_EVENT_TYPE, "closeout_complete")
        self.assertEqual(default_stage_for_event(CONTRACT_COMPLETION_EVENT_TYPE), "closeout")
        closeout_codes = {code for code, _label in settings_options(None, "event.type.closeout")}
        self.assertIn(CONTRACT_COMPLETION_EVENT_TYPE, closeout_codes)
        generic_options = event_workflow_options(None)["types_by_stage"]["closeout"]
        self.assertNotIn(CONTRACT_COMPLETION_EVENT_TYPE, {code for code, _label in generic_options})

    def test_contract_list_shows_four_workflow_phases_only(self):
        template = (
            ROOT / "templates" / "geoflow_ops" / "contracts" / "contract_list.html"
        ).read_text(encoding="utf-8")
        self.assertIn("업무단계", template)
        self.assertNotIn("운영상태", template)
        self.assertIn("data-workflow-phase", template)
        self.assertIn("planned: '계약'", template)
        self.assertIn("active: '진행'", template)
        self.assertIn("pause: '준공'", template)
        self.assertIn("complete: '완료'", template)
        self.assertIn("gf-k-cancel", template)

    def test_contract_detail_has_four_steps_and_completion_action(self):
        forms = (ROOT / "forms.py").read_text(encoding="utf-8")
        detail = (
            ROOT / "templates" / "geoflow_ops" / "contracts" / "contract_detail.html"
        ).read_text(encoding="utf-8")
        self.assertNotIn('settings_options(alias, "contract.status")', forms)
        self.assertNotIn('name="status"', detail)
        self.assertNotIn("운영상태", detail)
        for label in ("1. 계약", "2. 진행", "3. 준공", "4. 완료"):
            self.assertIn(label, detail)
        self.assertIn('id="btn-contract-complete"', detail)
        self.assertIn("contract_complete_action", detail)
        self.assertIn("event_type: 'closeout_complete'", detail)
        self.assertIn("stage: 'closeout'", detail)

    def test_event_modal_hides_processing_status_and_explains_stage_driven_flow(self):
        modal = (
            ROOT / "templates" / "geoflow_ops" / "events" / "_event_modal.html"
        ).read_text(encoding="utf-8")
        self.assertIn('class="d-none" id="event-status"', modal)
        self.assertNotIn("처리 상태", modal)
        self.assertIn("업무 단계", modal)
        self.assertIn("업무 유형이 기타여도 동일합니다", modal)
        self.assertIn("준공 완료", modal)
        self.assertNotIn('value="closeout_complete"', modal)
