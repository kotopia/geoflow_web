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
        self.assertIn('("webgisapp", "0020_phase4_project_task_execution")', migration)

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
        for role in ("tenant_admin", "tenant_manager", "project_manager", "project_leader", "viewer"):
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
        self.assertIn('request.method == "POST" and not policy.can_edit(emp_id)', boundary)
        self.assertIn("if not policy.can_create", boundary)
        self.assertIn("not policy.can_assign_roles", boundary)
        self.assertIn('ROLE_ASSIGN_PERMISSION = "directory.roles.assign"', boundary)

    def test_self_service_does_not_allow_self_promotion_fields(self):
        view = source("geoflow_ops/views_employee_profile.py")
        self.assertIn("if policy.can_edit_admin_fields", view)
        self.assertIn("SET name=%s, phone=%s, updated_at=now()", view)
        self.assertIn("position_grade", view)
        partial = source("geoflow_ops/templates/geoflow_ops/employees/_employee_profile_form.html")
        self.assertIn("{% if can_edit_admin_fields %}", partial)
        self.assertIn("조직·직급·고용상태·입퇴사 정보는 관리자 관리 항목", partial)

    def test_employee_page_has_separate_hr_sections(self):
        template = source("geoflow_ops/templates/geoflow_ops/employees/employee_detail.html")
        for label in ("기본정보", "학력", "자격", "기술등급", "경력"):
            self.assertIn(label, template)
        self.assertIn("이전회사 경력", template)
        self.assertIn("추후 프로젝트 배정에서 자동 누적", template)

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
        ):
            self.assertIn(path, preflight)


if __name__ == "__main__":
    unittest.main()
