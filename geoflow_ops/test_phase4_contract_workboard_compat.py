from pathlib import Path

from django.test import SimpleTestCase

from geoflow_ops.process_workflow import (
    CONTRACT_LIFECYCLE_MILESTONES,
    default_stage_for_event,
)
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

    def test_legacy_stage_helpers_remain_compatible(self):
        self.assertEqual(fallback_stage_for_contract_status("planned"), "pre_contract")
        self.assertEqual(fallback_stage_for_contract_status("active"), "execution")
        self.assertEqual(fallback_stage_for_contract_status("complete"), "closeout")
        self.assertEqual(major_phase_for_stage("kickoff"), ("execution", "수행(진행)"))

    def test_only_explicit_major_events_move_contract_lifecycle(self):
        self.assertEqual(
            CONTRACT_LIFECYCLE_MILESTONES,
            {
                "kickoff": ("execution", "착수"),
                "completion_doc": ("closeout", "준공계 제출"),
                "closeout_complete": ("closeout", "완료"),
            },
        )
        self.assertNotIn("kickoff_doc", CONTRACT_LIFECYCLE_MILESTONES)
        self.assertNotIn("contract_change", CONTRACT_LIFECYCLE_MILESTONES)
        self.assertNotIn("period_extension", CONTRACT_LIFECYCLE_MILESTONES)
        self.assertNotIn("suspend", CONTRACT_LIFECYCLE_MILESTONES)
        self.assertNotIn("resume", CONTRACT_LIFECYCLE_MILESTONES)
        self.assertNotIn("delivery", CONTRACT_LIFECYCLE_MILESTONES)
        self.assertNotIn("payment", CONTRACT_LIFECYCLE_MILESTONES)

    def test_eventless_contract_display_is_contract_created(self):
        summary = _stage_summary("contract", milestone_label="계약 생성")
        self.assertEqual(summary["major_code"], "contract")
        self.assertEqual(summary["major_label"], "계약")
        self.assertEqual(summary["major_event_label"], "계약 생성")
        self.assertEqual(summary["filter_key"], "planned")

    def test_kickoff_is_the_only_start_milestone(self):
        self.assertEqual(default_stage_for_event("kickoff"), "kickoff")
        self.assertEqual(default_stage_for_event("kickoff_doc"), "kickoff")
        self.assertIn("kickoff", CONTRACT_LIFECYCLE_MILESTONES)
        self.assertNotIn("kickoff_doc", CONTRACT_LIFECYCLE_MILESTONES)

    def test_closeout_and_final_completion_are_distinct(self):
        in_closeout = _stage_summary(
            "closeout",
            is_complete=False,
            milestone_label="준공계 제출",
        )
        completed = _stage_summary(
            "closeout",
            is_complete=True,
            milestone_label="완료",
        )
        self.assertEqual(in_closeout["major_label"], "준공")
        self.assertEqual(in_closeout["major_event_label"], "준공계 제출")
        self.assertFalse(in_closeout["is_complete"])
        self.assertEqual(completed["major_event_label"], "완료")
        self.assertTrue(completed["is_complete"])
        self.assertNotEqual(in_closeout["phase_class"], completed["phase_class"])

    def test_completion_event_is_available_to_legacy_configured_tenants(self):
        self.assertEqual(default_stage_for_event("closeout_complete"), "closeout")
        closeout_options = dict(settings_options(None, "event.type.closeout"))
        self.assertEqual(closeout_options.get("closeout_complete"), "완료")

    def test_contract_workflow_service_does_not_use_contract_status(self):
        source = (ROOT / "services" / "workflow_state.py").read_text(encoding="utf-8")
        lifecycle_body = source.split("def contract_workflow_summaries", 1)[1]
        self.assertIn("CONTRACT_LIFECYCLE_MILESTONES", lifecycle_body)
        self.assertNotIn("contract.status", lifecycle_body.lower())
        self.assertNotIn("UPDATE ctr.contracts", source)
        self.assertIn("kickoff_doc", source)
        self.assertIn("does not start 진행", source)

    def test_contract_list_shows_only_event_derived_work_phase(self):
        template = (
            ROOT / "templates" / "geoflow_ops" / "contracts" / "contract_list.html"
        ).read_text(encoding="utf-8")
        self.assertIn("업무단계", template)
        self.assertNotIn("운영상태", template)
        self.assertIn("wf.major_event_label", template)
        self.assertIn("data-workflow-phase", template)
        self.assertIn("gf-k-pause", template)
        self.assertIn("gf-k-cancel", template)

    def test_contract_form_and_detail_do_not_expose_contract_status(self):
        forms = (ROOT / "forms.py").read_text(encoding="utf-8")
        detail = (
            ROOT / "templates" / "geoflow_ops" / "contracts" / "contract_detail.html"
        ).read_text(encoding="utf-8")
        self.assertNotIn('settings_options(alias, "contract.status")', forms)
        self.assertNotIn('"status", "kind"', forms)
        self.assertNotIn('name="status"', detail)
        self.assertNotIn("운영상태", detail)
        self.assertIn("착수 → 준공계 제출 → 완료", detail)
        self.assertIn("gf-lifecycle", detail)

    def test_event_modal_hides_processing_status_from_user(self):
        modal = (
            ROOT / "templates" / "geoflow_ops" / "events" / "_event_modal.html"
        ).read_text(encoding="utf-8")
        self.assertIn('type="hidden" id="event-status" value="open"', modal)
        self.assertNotIn("처리 상태", modal)
        self.assertIn("착수 → 진행", modal)
        self.assertIn("준공계 제출 → 준공", modal)
        self.assertIn("완료 → 준공 완료", modal)
