from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parent


class ContractWorkboardCompatibilityTests(SimpleTestCase):
    def test_contract_timeline_client_consumes_cross_department_fields(self):
        source = (
            ROOT / "static" / "geoflow_ops" / "js" / "process-events-ui.js"
        ).read_text(encoding="utf-8")

        self.assertIn("deriveAssignmentOptionsUrl", source)
        self.assertIn("assignment-options/", source)
        self.assertIn("ev.can_write", source)
        self.assertIn("ev.owner_department_name", source)
        self.assertIn("ev.assignee_employee_name", source)
        self.assertIn("ev.project_name", source)
        self.assertIn("ev.due_at", source)

    def test_contract_timeline_sends_assignment_only_when_authorized(self):
        source = (
            ROOT / "static" / "geoflow_ops" / "js" / "process-events-ui.js"
        ).read_text(encoding="utf-8")

        self.assertIn("if (config.canAssign)", source)
        self.assertIn("payload.owner_department_id", source)
        self.assertIn("payload.assignee_employee_id", source)
        self.assertIn("due_at: fDue", source)
        self.assertIn("currentCanWrite", source)

    def test_contract_timeline_preserves_event_scope_for_merged_project_events(self):
        source = (
            ROOT / "static" / "geoflow_ops" / "js" / "process-events-ui.js"
        ).read_text(encoding="utf-8")

        self.assertIn("currentEvent.scope_type", source)
        self.assertIn("currentEvent.scope_id", source)
        self.assertIn("currentEvent = ev", source)

    def test_contract_timeline_uses_void_language_not_physical_delete_language(self):
        source = (
            ROOT / "static" / "geoflow_ops" / "js" / "process-events-ui.js"
        ).read_text(encoding="utf-8")

        self.assertIn("취소 처리", source)
        self.assertIn("이력은 삭제되지 않습니다", source)
        self.assertNotIn("정말 이 이벤트를 삭제하시겠습니까", source)

    def test_contract_detail_still_uses_shared_event_endpoint(self):
        template = (
            ROOT / "templates" / "geoflow_ops" / "contracts" / "contract_detail.html"
        ).read_text(encoding="utf-8")
        urls = (ROOT / "urls.py").read_text(encoding="utf-8")
        security = (ROOT / "event_security_views.py").read_text(encoding="utf-8")

        self.assertIn("tenant:event_list", template)
        self.assertIn("process-events-ui.js", template)
        self.assertIn("event_security_views.event_list", urls)
        self.assertIn("views_workboard.workboard_event_list", security)
