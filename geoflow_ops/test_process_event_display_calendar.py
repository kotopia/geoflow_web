from pathlib import Path

from django.test import SimpleTestCase

from geoflow_ops.process_workflow import (
    EVENT_DEFAULT_STAGE,
    EVENT_TRANSITION_TARGETS,
    STAGE_CHOICES,
    transition_stage_for_event,
)
from geoflow_ops.services.tenant_settings import event_workflow_options, settings_options

ROOT = Path(__file__).resolve().parent


def source(path):
    return (ROOT / path).read_text(encoding="utf-8")


class ProcessEventDisplayCalendarTests(SimpleTestCase):
    def test_environment_process_stage_is_exact_six_stage_lifecycle(self):
        expected = [
            ("preparation", "준비"), ("contract", "계약"),
            ("kickoff", "착수"), ("execution", "수행"),
            ("closeout", "준공"), ("complete", "완료"),
        ]
        self.assertEqual([(x.code, x.label) for x in STAGE_CHOICES], expected)
        self.assertEqual(list(settings_options(None, "event.stage")), expected)
        settings_view = source("views_settings.py")
        self.assertIn("_ensure_canonical_stage_nodes", settings_view)
        self.assertIn("GeoFlow 필수 Process Stage", settings_view)

    def test_settlement_is_event_only_and_never_process_transition(self):
        self.assertEqual(EVENT_DEFAULT_STAGE["advance_payment"], "settlement")
        self.assertEqual(EVENT_DEFAULT_STAGE["progress_payment"], "settlement")
        self.assertEqual(EVENT_DEFAULT_STAGE["final_payment"], "settlement")
        self.assertIsNone(transition_stage_for_event("advance_payment"))
        self.assertIsNone(transition_stage_for_event("progress_payment"))
        self.assertIsNone(transition_stage_for_event("final_payment"))
        self.assertNotIn("settlement", EVENT_TRANSITION_TARGETS.values())
        options = event_workflow_options(None)
        self.assertIn(("settlement", "정산"), options["stages"])
        self.assertEqual(dict(options["types_by_stage"]["settlement"]), {
            "advance_payment": "선급금", "progress_payment": "기성금", "final_payment": "준공금",
        })
        self.assertNotIn(("settlement", "정산"), options["process_stages"])

    def test_completion_has_no_redundant_complete_event(self):
        self.assertEqual(transition_stage_for_event("closeout_approved"), "complete")
        self.assertEqual(event_workflow_options(None)["types_by_stage"]["complete"], [])

    def test_event_modal_uses_occurred_and_end_dates_only(self):
        modal = source("templates/geoflow_ops/events/_event_modal.html")
        self.assertIn("event-occurred-at", modal)
        self.assertIn("event-end-at", modal)
        self.assertIn("캘린더에 추가", modal)
        self.assertNotIn("완료 예정일", modal)
        self.assertNotIn("event-due-at", modal)
        self.assertNotIn("event-highlight-enabled", modal)
        self.assertNotIn("event-highlight-days", modal)
        self.assertNotIn("event-until-closed", modal)

    def test_legacy_due_at_is_migrated_to_end_at(self):
        migration = source("migrations/0028_move_due_at_to_event_end_at.py")
        self.assertIn("to_char(due_at, 'YYYY-MM-DD')", migration)
        self.assertIn("'end_at'", migration)
        self.assertIn("SET due_at = NULL", migration)

    def test_current_stage_badges_use_exact_event_type_labels(self):
        workflow = source("services/workflow_state.py")
        js = source("static/geoflow_ops/js/process-event-display-calendar.js")
        contract_list = source("templates/geoflow_ops/contracts/contract_list.html")
        project_list = source("templates/geoflow_ops/projects/project_list.html")
        self.assertIn("active_event_labels", workflow)
        self.assertIn("suspend:'중지'", js)
        self.assertIn("resume:'재개'", js)
        self.assertNotIn("용역 중지", js)
        self.assertNotIn("용역 재개", js)
        self.assertIn("wf.active_event_labels", contract_list)
        self.assertIn("wf.active_event_labels", project_list)
        self.assertNotIn("insertAdjacentElement('afterend'", js)

    def test_calendar_page_and_feed_are_wired(self):
        urls = source("urls.py")
        sidebar = source("templates/geoflow_ops/partials/sidebar.html")
        template = source("templates/geoflow_ops/calendar/calendar.html")
        view = source("views_calendar.py")
        self.assertIn("calendar/", urls)
        self.assertIn("api/calendar/events/", urls)
        self.assertIn("tenant:calendar", sidebar)
        self.assertIn("FullCalendar.Calendar", template)
        self.assertIn('display["calendar_enabled"]', view)
        self.assertIn("authorize_scope_read", view)

    def test_detail_process_bar_is_horizontal_timeline_styled(self):
        css = source("static/geoflow_ops/css/process-timeline-horizontal.css")
        base = source("templates/geoflow_ops/base_tenant.html")
        contract = source("templates/geoflow_ops/contracts/contract_detail.html")
        project = source("templates/geoflow_ops/projects/project_detail.html")
        self.assertIn('[aria-label="업무 프로세스"]', css)
        self.assertIn("gf-stage-complete", css)
        self.assertIn("process-timeline-horizontal.css", base)
        for label in ("1. 준비", "2. 계약", "3. 착수", "4. 수행", "5. 준공", "6. 완료"):
            self.assertIn(label, contract)
            self.assertIn(label, project)
