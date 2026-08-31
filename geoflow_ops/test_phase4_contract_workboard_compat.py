from pathlib import Path

from django.test import SimpleTestCase

from geoflow_ops.process_workflow import (
    CONTRACT_COMPLETION_EVENT_TYPE,
    CONTRACT_LIFECYCLE_STAGE_PHASES,
    REQUIRED_EVENT_STAGE_CODES,
    default_stage_for_event,
    transition_stage_for_event,
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

    def test_contract_timeline_uses_user_delete_language_but_retains_logical_history(self):
        source = self._client_source()
        self.assertIn("이 이벤트를 삭제할까요?", source)
        self.assertIn("이력 보존", source)
        self.assertIn("window.location.reload()", source)
        self.assertNotIn("취소 처리", source)
        backend = (ROOT / "views_events.py").read_text(encoding="utf-8")
        self.assertIn('event.status = "void"', backend)
        self.assertNotIn("event.delete()", backend)

    def test_contract_timeline_uses_configurable_stage_type_workflow(self):
        source = self._client_source()
        self.assertIn("workflowOptionsUrl", source)
        self.assertIn("types_by_stage", source)
        self.assertIn("function populateEventTypes", source)
        self.assertIn("fStage.onchange", source)
        self.assertIn("workflow options unavailable", source)
        self.assertNotIn("pre_contract: [{code:'estimate'", source)

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

    def test_stage_helpers_report_exact_six_stage_model_and_runtime_is_event_derived(self):
        self.assertEqual(fallback_stage_for_contract_status("planned"), "preparation")
        self.assertEqual(fallback_stage_for_contract_status("active"), "execution")
        self.assertEqual(fallback_stage_for_contract_status("complete"), "complete")
        self.assertEqual(major_phase_for_stage("kickoff"), ("kickoff", "착수"))
        source = (ROOT / "services" / "workflow_state.py").read_text(encoding="utf-8")
        runtime = source.split("def contract_workflow_summaries", 1)[1]
        self.assertNotIn('getattr(contract, "status"', runtime)
        self.assertIn("event-derived", source)
        self.assertIn("transition_stage_for_event", runtime)

    def test_contract_lifecycle_is_exact_six_stage_and_event_transition_driven(self):
        self.assertEqual(
            tuple(CONTRACT_LIFECYCLE_STAGE_PHASES),
            ("preparation", "contract", "kickoff", "execution", "closeout", "complete"),
        )
        self.assertEqual(transition_stage_for_event("contract_signed"), "contract")
        self.assertEqual(transition_stage_for_event("kickoff_submitted"), "kickoff")
        self.assertEqual(transition_stage_for_event("kickoff_approved"), "execution")
        self.assertEqual(transition_stage_for_event("closeout_submitted"), "closeout")
        self.assertEqual(transition_stage_for_event("closeout_approved"), "complete")
        self.assertIsNone(transition_stage_for_event("suspend"))
        self.assertIsNone(transition_stage_for_event("resume"))
        self.assertNotIn("billing", CONTRACT_LIFECYCLE_STAGE_PHASES)
        source = (ROOT / "services" / "workflow_state.py").read_text(encoding="utf-8")
        self.assertIn("highest reached transition wins", source)
        self.assertNotIn("phase = CONTRACT_LIFECYCLE_STAGE_PHASES.get(stage)", source)

    def test_required_event_stages_are_canonical_and_always_available(self):
        stages = dict(settings_options(None, "event.stage"))
        for code in REQUIRED_EVENT_STAGE_CODES:
            self.assertIn(code, stages)
        self.assertEqual(stages["preparation"], "준비")
        self.assertEqual(stages["contract"], "계약")
        self.assertEqual(stages["kickoff"], "착수")
        self.assertEqual(stages["execution"], "수행")
        self.assertEqual(stages["closeout"], "준공")
        self.assertEqual(stages["complete"], "완료")

    def test_eventless_contract_display_is_preparation(self):
        summary = _stage_summary("preparation")
        self.assertEqual(summary["major_code"], "preparation")
        self.assertEqual(summary["major_label"], "준비")
        self.assertEqual(summary["filter_key"], "planned")

    def test_kickoff_is_visible_as_distinct_stage(self):
        self.assertEqual(default_stage_for_event("kickoff_submitted"), "kickoff")
        summary = _stage_summary("kickoff")
        self.assertEqual(summary["major_code"], "kickoff")
        self.assertEqual(summary["major_label"], "착수")
        self.assertEqual(summary["filter_key"], "active")

    def test_closeout_and_complete_are_distinct_process_stages(self):
        in_closeout = _stage_summary("closeout")
        completed = _stage_summary("complete")
        self.assertEqual(in_closeout["major_code"], "closeout")
        self.assertEqual(in_closeout["major_label"], "준공")
        self.assertEqual(in_closeout["filter_key"], "pause")
        self.assertFalse(in_closeout["is_complete"])
        self.assertEqual(completed["major_code"], "complete")
        self.assertEqual(completed["major_label"], "완료")
        self.assertEqual(completed["filter_key"], "complete")
        self.assertTrue(completed["is_complete"])

    def test_logically_deleted_event_is_hidden_and_cannot_drive_visible_lifecycle(self):
        workboard = (ROOT / "views_workboard.py").read_text(encoding="utf-8")
        workflow = (ROOT / "services" / "workflow_state.py").read_text(encoding="utf-8")
        self.assertIn('.exclude(status="void")', workboard)
        self.assertIn("COALESCE(status, '') <> 'void'", workflow)
        self.assertIn("highest reached transition wins", workflow)

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

    def test_closeout_approval_is_canonical_completion_and_is_selectable(self):
        self.assertEqual(CONTRACT_COMPLETION_EVENT_TYPE, "closeout_approved")
        self.assertEqual(default_stage_for_event(CONTRACT_COMPLETION_EVENT_TYPE), "closeout")
        self.assertEqual(transition_stage_for_event(CONTRACT_COMPLETION_EVENT_TYPE), "complete")
        closeout_codes = {code for code, _label in settings_options(None, "event.type.closeout")}
        self.assertIn(CONTRACT_COMPLETION_EVENT_TYPE, closeout_codes)
        generic_options = event_workflow_options(None)["types_by_stage"]["closeout"]
        self.assertIn(CONTRACT_COMPLETION_EVENT_TYPE, {code for code, _label in generic_options})

    def test_contract_list_keeps_shared_filter_groups_over_exact_process_stage(self):
        template = (
            ROOT / "templates" / "geoflow_ops" / "contracts" / "contract_list.html"
        ).read_text(encoding="utf-8")
        self.assertIn('data-col="workflow"', template)
        self.assertNotIn("운영상태", template)
        self.assertIn("data-workflow-phase", template)
        self.assertIn("planned: '계약'", template)
        self.assertIn("active: '진행'", template)
        self.assertIn("pause: '준공'", template)
        self.assertIn("complete: '완료'", template)
        self.assertIn("gf-k-cancel", template)

    def test_contract_detail_retains_existing_completion_button_as_legacy_client(self):
        forms = (ROOT / "forms.py").read_text(encoding="utf-8")
        detail = (
            ROOT / "templates" / "geoflow_ops" / "contracts" / "contract_detail.html"
        ).read_text(encoding="utf-8")
        security = (ROOT / "event_security_views.py").read_text(encoding="utf-8")
        self.assertNotIn('settings_options(alias, "contract.status")', forms)
        self.assertNotIn('name="status"', detail)
        self.assertNotIn("운영상태", detail)
        self.assertIn('id="btn-contract-complete"', detail)
        self.assertIn("event_type: 'closeout_complete'", detail)
        self.assertIn("normalize_event_type_for_write", security)
        self.assertIn("closeout_complete -> closeout_approved", security)

    def test_event_modal_is_compact_settings_driven_and_keeps_metadata_collapsed(self):
        modal = (
            ROOT / "templates" / "geoflow_ops" / "events" / "_event_modal.html"
        ).read_text(encoding="utf-8")
        self.assertIn('class="d-none" id="event-status"', modal)
        self.assertNotIn("처리 상태", modal)
        self.assertIn("업무 단계", modal)
        self.assertIn("환경설정 불러오는 중", modal)
        self.assertIn('data-bs-toggle="collapse"', modal)
        self.assertIn("상세 정보", modal)
        self.assertIn('id="event-updated-at"', modal)
        self.assertIn('id="btn-delete-event-modal">삭제', modal)
        self.assertNotIn("modal-lg", modal)
        self.assertNotIn('value="pre_contract"', modal)
        self.assertNotIn('value="closeout_complete"', modal)
