from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class Phase4EmployeeSettingsFoundationTests(unittest.TestCase):
    def test_employee_history_migration_is_additive_and_project_history_is_deferred(self):
        migration = source("geoflow_ops/migrations/0021_phase4_employee_settings_foundation.py")
        lowered = migration.lower()
        for table in (
            "hr.employee_education",
            "hr.employee_qualification",
            "hr.employee_technical_grade",
            "hr.employee_career",
            "ops.settings_nodes",
        ):
            self.assertIn(f"create table if not exists {table}", lowered)
        for destructive in (
            "delete from hr.employee_profile",
            "truncate hr.employee_profile",
            "drop table hr.employee_profile",
            "delete from ops.attachments",
            "truncate ops.attachments",
        ):
            self.assertNotIn(destructive, lowered)
        self.assertNotIn("employee_project_history", lowered)
        self.assertIn('(\"webgisapp\", \"0020_phase4_project_task_execution\")', migration)

    def test_settings_tree_is_platform_wide_and_not_employee_specific(self):
        migration = source("geoflow_ops/migrations/0021_phase4_employee_settings_foundation.py")
        for system_key in (
            "domain.hr",
            "domain.contract",
            "domain.project",
            "domain.event",
            "domain.gis",
            "hr.position_grade",
            "hr.position_title",
            "hr.employment_type",
            "hr.status",
            "hr.technical_grade",
        ):
            self.assertIn(system_key, migration)
        view = source("geoflow_ops/views_settings.py").lower()
        self.assertNotIn("delete from ops.settings_nodes", view)
        self.assertIn("active", view)
        self.assertIn("parent_id", view)

    def test_employee_access_policy_matches_reviewed_role_boundaries(self):
        policy = source("geoflow_ops/services/employee_access.py")
        for role in (
            "tenant_admin",
            "tenant_manager",
            "project_admin",
            "project_coordinator",
            "project_manager",
            "project_leader",
            "viewer",
        ):
            self.assertIn(role, policy)
        self.assertIn('mode = "full"', policy)
        self.assertIn('mode = "all_view"', policy)
        self.assertIn('mode = "self"', policy)
        self.assertIn("def can_view", policy)
        self.assertIn("def can_edit", policy)
        self.assertIn("def can_edit_admin_fields", policy)

        boundary = source("geoflow_ops/employee_security_views.py")
        self.assertIn("if not policy.can_list", boundary)
        self.assertIn("if not policy.can_view(emp_id)", boundary)
        self.assertIn('if request.method == "POST":', boundary)
        self.assertIn("if not policy.can_edit(emp_id)", boundary)
        self.assertIn('gf_has_perm(request, "directory.edit")', boundary)
        self.assertIn("if not policy.can_create", boundary)
        self.assertIn("not policy.can_assign_roles", boundary)
        self.assertIn('gf_has_perm(request, "directory.roles.assign")', boundary)

    def test_self_service_does_not_allow_self_promotion_fields(self):
        view = source("geoflow_ops/views_employee_profile.py")
        self.assertIn("if policy.can_edit_admin_fields", view)
        self.assertIn("SET name=%s, phone=%s, addr_road=%s, addr_detail=%s, addr_zip=%s", view)
        self.assertIn("position_grade", view)
        partial = source("geoflow_ops/templates/geoflow_ops/employees/_employee_profile_form.html")
        self.assertIn("{% if can_edit_admin_fields %}", partial)
        self.assertIn("조직·직급·고용상태·입퇴사 정보는 관리자 관리 항목", partial)

    def test_employee_page_has_separate_hr_sections(self):
        template = source("geoflow_ops/templates/geoflow_ops/employees/employee_detail.html")
        for label in ("기본정보", "학력", "자격", "기술등급", "경력"):
            self.assertIn(label, template)
        self.assertIn("이전회사 경력", template)
        self.assertIn("프로젝트 참여정보에서 관리", template)

    def test_employee_detail_uses_adminkit_summary_and_card_tabs(self):
        template = source("geoflow_ops/templates/geoflow_ops/employees/employee_detail.html")
        self.assertIn('class="nav nav-tabs"', template)
        self.assertIn('id="employeeTabs"', template)
        self.assertIn("{% employee_summary", template)
        self.assertIn("근무연수", template)
        self.assertIn("참여 프로젝트", template)
        self.assertIn("qualification_badges", template)
        self.assertIn("technical_badges", template)
        self.assertIn("summary.status_class", template)
        presenter = source("geoflow_ops/templatetags/employee_ui.py")
        self.assertIn('"퇴사": "bg-secondary"', presenter)
        self.assertIn('"project_admin": "프로젝트 관리자"', presenter)
        self.assertIn('"project_coordinator": "프로젝트 코디네이터"', presenter)
        self.assertIn("COUNT(DISTINCT project_id)", presenter)

    def test_employee_history_documents_are_record_scoped_and_verified(self):
        view = source("geoflow_ops/views_employee_history.py")
        for table in (
            "hr.employee_education",
            "hr.employee_qualification",
            "hr.employee_technical_grade",
            "hr.employee_career",
        ):
            self.assertIn(table, view)
        self.assertIn('HISTORY_DOCUMENT_PURPOSE = "history_doc"', view)
        self.assertIn("WHERE id=%s AND employee_id=%s AND active=true", view)
        self.assertIn("head_private_object", view)
        self.assertIn("metadata.encryption_matches", view)
        self.assertIn('kind=_history_kind(section, record_id)', view)
        self.assertIn('meta={"history_section": section, "history_record_id": str(record_id)}', view)

        template = source("geoflow_ops/templates/geoflow_ops/employees/employee_detail.html")
        self.assertIn('id="employeeHistoryModal"', template)
        self.assertIn('id="history-file-input"', template)
        self.assertIn("multiple", template)
        self.assertIn("base + 'presign/'", template)
        self.assertIn("base + 'commit/'", template)
        self.assertIn("uploadHistoryFile", template)

    def test_employee_history_routes_remain_under_employee_security_boundary(self):
        urls = source("geoflow_ops/urls.py")
        boundary = source("geoflow_ops/employee_security_views.py")
        preflight = source("control/services/route_security_preflight.py")
        for route_name in (
            "employee_history_save",
            "employee_history_attachment_presign",
            "employee_history_attachment_commit",
        ):
            self.assertIn(route_name, urls)
            self.assertIn(f"def {route_name}", boundary)
            self.assertIn(route_name, preflight)
        self.assertGreaterEqual(boundary.count("if not policy.can_edit(emp_id)"), 4)

    def test_preview_and_download_are_distinct_user_actions(self):
        template = source("geoflow_ops/templates/geoflow_ops/employees/employee_detail.html")
        self.assertIn("tenant:upload_preview", template)
        self.assertIn("btn-download-doc", template)
        self.assertIn("getPresignedGetUrl(button.dataset.attId, csrfToken, 'download')", template)

        guard = source("geoflow_ops/upload_guard_views.py")
        self.assertIn("def preview(request, attachment_id)", guard)
        self.assertIn('disposition="inline"', guard)
        self.assertIn('mode not in {"inline", "download"}', guard)
        self.assertIn('disposition = "inline" if inline_allowed else "attachment"', guard)

    def test_new_sensitive_routes_are_under_reviewed_boundaries(self):
        preflight = source("control/services/route_security_preflight.py")
        for path in (
            '"/employees/me/"',
            '"/settings/"',
            '"/settings/node/save/"',
            'f"/attachments/preview/{_UUID}/"',
            'f"/employees/{_UUID}/history/save/"',
        ):
            self.assertIn(path, preflight)


if __name__ == "__main__":
    unittest.main()
