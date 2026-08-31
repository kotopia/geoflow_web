from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parent


class WorkboardSourceContracts(SimpleTestCase):
    def test_event_workboard_scope_access_is_fail_closed(self):
        source = (ROOT / "views_workboard.py").read_text(encoding="utf-8")
        self.assertIn("authorize_scope_write(request, alias, event.scope_type, event.scope_id)", source)
        self.assertIn("scope_can_write = bool(authorize_scope_write(request, alias, scope_type, scope_id))", source)
        self.assertIn("authorize_scope_read(request, alias, scope_type, scope_id)", source)
        self.assertIn("require_tenant_context(request)", source)
        self.assertNotIn('item["can_write"] = bool(has_scope_permission(request, event.scope_type, write=True))', source)

    def test_assignment_write_routes_use_server_side_directory_guard(self):
        guard_source = (ROOT / "event_security_views.py").read_text(encoding="utf-8")
        url_source = (ROOT / "urls.py").read_text(encoding="utf-8")
        self.assertIn('not gf_has_perm(\n        request, "directory.view"', guard_source)
        self.assertIn("ASSIGNMENT_FIELDS", guard_source)
        self.assertIn("event_security_views.event_create", url_source)
        self.assertIn("event_security_views.event_update", url_source)

    def test_modal_exposes_assignment_and_event_end_date_controls(self):
        source = (
            ROOT / "templates" / "geoflow_ops" / "events" / "_event_modal.html"
        ).read_text(encoding="utf-8")
        self.assertIn('id="event-owner-department"', source)
        self.assertIn('id="event-assignee-employee"', source)
        self.assertIn('id="event-occurred-at"', source)
        self.assertIn('id="event-end-at"', source)
        self.assertNotIn('id="event-due-at"', source)
        self.assertNotIn("완료 예정일", source)

    def test_project_detail_wires_workboard_summary_and_assignment_api(self):
        source = (
            ROOT / "templates" / "geoflow_ops" / "projects" / "project_detail.html"
        ).read_text(encoding="utf-8")
        for token in (
            'id="project-scope-pane"',
            'id="project-timeline-pane"',
            'id="project-members-pane"',
            'id="timelineList"',
            'data-assignment-options-url=',
            "process-workboard-ui.js",
            "ProcessWorkboardUI.init",
        ):
            self.assertIn(token, source)
