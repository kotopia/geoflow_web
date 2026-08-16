from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from django.db.models import Q
from django.test import SimpleTestCase

from geoflow_ops.views_workboard import _event_filter


ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent


def _q_leaves(node):
    leaves = []
    if not isinstance(node, Q):
        return leaves
    for child in node.children:
        if isinstance(child, Q):
            leaves.extend(_q_leaves(child))
        else:
            leaves.append(child)
    return leaves


class IntegratedTimelineFilterTests(SimpleTestCase):
    @patch("geoflow_ops.views_workboard.has_scope_permission", return_value=True)
    def test_contract_timeline_includes_project_events_only_with_project_read_permission(self, _permission_mock):
        contract_id = uuid4()
        query, mode = _event_filter(object(), "tenant", "contract", contract_id)
        leaves = _q_leaves(query)

        self.assertEqual(mode, "contract_with_projects")
        self.assertIn(("scope_type", "contract"), leaves)
        self.assertIn(("scope_id", contract_id), leaves)
        self.assertIn(("scope_type", "project"), leaves)
        self.assertIn(("contract_id", contract_id), leaves)

    @patch("geoflow_ops.views_workboard.has_scope_permission", return_value=False)
    def test_contract_timeline_falls_back_to_contract_only_without_project_permission(self, _permission_mock):
        contract_id = uuid4()
        query, mode = _event_filter(object(), "tenant", "contract", contract_id)
        leaves = _q_leaves(query)

        self.assertEqual(mode, "contract_only")
        self.assertIn(("scope_type", "contract"), leaves)
        self.assertIn(("scope_id", contract_id), leaves)
        self.assertNotIn(("contract_id", contract_id), leaves)

    @patch("geoflow_ops.views_workboard._project_contract_id")
    @patch("geoflow_ops.views_workboard.has_scope_permission", return_value=True)
    def test_project_timeline_includes_parent_contract_when_contract_read_is_allowed(
        self, _permission_mock, contract_lookup_mock
    ):
        project_id = uuid4()
        contract_id = uuid4()
        contract_lookup_mock.return_value = contract_id

        query, mode = _event_filter(object(), "tenant", "project", project_id)
        leaves = _q_leaves(query)

        self.assertEqual(mode, "project_with_contract")
        self.assertIn(("scope_type", "project"), leaves)
        self.assertIn(("scope_id", project_id), leaves)
        self.assertIn(("scope_type", "contract"), leaves)
        self.assertIn(("scope_id", contract_id), leaves)


class WorkboardSourceContracts(SimpleTestCase):
    def test_assignment_options_are_tenant_directory_scoped_and_minimal(self):
        source = (ROOT / "views_workboard.py").read_text(encoding="utf-8")
        self.assertIn('gf_has_perm(request, "directory.view")', source)
        self.assertIn("FROM hr.departments", source)
        self.assertIn("FROM hr.employee_profile", source)
        self.assertIn("status <> '퇴사'", source)
        self.assertNotIn("SELECT id::text, email", source)
        self.assertNotIn("phone", source)

    def test_integrated_timeline_preserves_per_event_write_authorization(self):
        source = (ROOT / "views_workboard.py").read_text(encoding="utf-8")
        self.assertIn('item["can_write"] = bool(has_scope_permission(request, event.scope_type, write=True))', source)
        self.assertIn("authorize_scope_read(request, alias, scope_type, scope_id)", source)
        self.assertIn("require_tenant_context(request)", source)

    def test_modal_exposes_assignment_and_due_date_controls(self):
        source = (
            ROOT / "templates" / "geoflow_ops" / "events" / "_event_modal.html"
        ).read_text(encoding="utf-8")
        self.assertIn('id="event-owner-department"', source)
        self.assertIn('id="event-assignee-employee"', source)
        self.assertIn('id="event-due-at"', source)

    def test_project_detail_wires_workboard_summary_and_assignment_api(self):
        source = (
            ROOT / "templates" / "geoflow_ops" / "projects" / "project_detail.html"
        ).read_text(encoding="utf-8")
        for token in (
            'id="workflowStage"',
            'id="workflowNextTask"',
            'id="workflowAssignee"',
            'id="workflowOpenCount"',
            'data-assignment-options-url=',
            "process-workboard-ui.js",
            "ProcessWorkboardUI.init",
        ):
            self.assertIn(token, source)
        self.assertNotIn("ProcessEventsUI.init", source)

    def test_project_summary_surfaces_all_projects_under_contract(self):
        source = (
            ROOT / "templates" / "geoflow_ops" / "projects" / "project_summary.html"
        ).read_text(encoding="utf-8")
        self.assertIn("project.contract.project_set.all", source)
        self.assertIn("1:N 계약 구조", source)
        self.assertIn("tenant:project_detail", source)

    def test_workboard_javascript_sends_assignment_only_when_authorized(self):
        source = (
            ROOT / "static" / "geoflow_ops" / "js" / "process-workboard-ui.js"
        ).read_text(encoding="utf-8")
        self.assertIn("if (config.canAssign)", source)
        self.assertIn("payload.owner_department_id", source)
        self.assertIn("payload.assignee_employee_id", source)
        self.assertIn("ev.can_write", source)

    def test_production_deploy_is_exact_release_protected_and_application_only(self):
        source = (
            REPO_ROOT / ".github" / "workflows" / "phase4-workboard-production-deploy.yml"
        ).read_text(encoding="utf-8")
        lowered = source.lower()
        self.assertIn("environment: production", source)
        self.assertIn("service='geoflow-stabilized.service'", source)
        self.assertIn('test "$(git rev-parse FETCH_HEAD)" = "$GITHUB_SHA"', source)
        self.assertIn("candidate_sha_not_current_release_head", source)
        self.assertIn("https://geoflow.co.kr/login/", source)
        self.assertNotIn("iroomsng", lowered)
        self.assertNotIn(" manage.py migrate", lowered)
        self.assertNotIn("migrate_all_tenants", lowered)
        self.assertNotIn("psql ", lowered)
        self.assertNotIn("delete from ", lowered)
        self.assertNotIn("truncate ", lowered)
