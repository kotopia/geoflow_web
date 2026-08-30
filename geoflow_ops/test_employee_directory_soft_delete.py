from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parent


def source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


class EmployeeDirectoryStatusTests(TestCase):
    def test_employee_list_uses_hr_status_settings_instead_of_contract_statuses(self):
        view = source("views_employee_profile.py")
        script = source("static/geoflow_ops/js/hr-list.js")
        template = source("templates/geoflow_ops/employees/employee_list.html")

        self.assertIn('"status": "hr.status"', view)
        self.assertIn("_employment_status_options", view)
        self.assertIn('json_script:"employee-status-options"', template)
        self.assertIn("employee-status-options", script)
        self.assertNotIn("GeoFlowListCore.initTable", script)
        for contract_status in ("계약전", "진행", "중지", "취소", "완료"):
            self.assertNotIn(contract_status, script)


class EmployeeSoftDeleteContractTests(TestCase):
    def test_migration_is_additive_and_keeps_audit_metadata(self):
        migration = source("migrations/0027_employee_profile_soft_delete.py").lower()
        for column in (
            "is_deleted",
            "deleted_at",
            "deleted_by",
            "delete_reason",
            "restored_at",
            "restored_by",
        ):
            self.assertIn(column, migration)
        self.assertIn("add column if not exists", migration)
        self.assertNotIn("delete from hr.employee_profile", migration)

    def test_delete_and_restore_are_post_only_and_permission_wrapped(self):
        security = source("employee_security_views.py")
        urls = source("urls.py")
        self.assertIn("def employee_soft_delete", security)
        self.assertIn("def employee_restore", security)
        self.assertGreaterEqual(security.count("@require_POST"), 4)
        self.assertIn('gf_has_perm(request, "directory.edit")', security)
        self.assertIn("employee_security_views.employee_soft_delete", urls)
        self.assertIn("employee_security_views.employee_restore", urls)

    def test_soft_delete_requires_retired_status_and_never_deletes_row(self):
        view = source("views_employee_profile.py").lower()
        self.assertIn("update hr.employee_profile", view)
        self.assertIn("set is_deleted=true", view)
        self.assertIn("status = any", view)
        self.assertIn("delete_reason", view)
        self.assertNotIn("delete from hr.employee_profile", view)

    def test_deleted_people_are_excluded_from_active_identity_and_assignment_pools(self):
        for relative_path in (
            "services/employee_access.py",
            "services/entity_access.py",
            "views_project_members.py",
            "views_workboard.py",
            "views_execution.py",
            "views_dashboard.py",
        ):
            with self.subTest(relative_path=relative_path):
                self.assertIn("is_deleted", source(relative_path))


class EmployeeRoleRequestRegressionTests(TestCase):
    def test_security_wrapper_passes_authoritative_tenant_alias(self):
        security = source("employee_security_views.py")
        role_view = source("views_employee_role_request.py")
        self.assertIn("alias, policy = _policy(request)", security)
        self.assertIn("alias=alias", security)
        self.assertIn("def employees_request_role_safe(request, emp_id, *, alias: str)", role_view)
        self.assertNotIn("current_db_alias", role_view)
        self.assertNotIn("@require_perm", role_view)

    def test_role_list_database_failure_is_handled_without_500(self):
        role_view = source("views_employee_role_request.py")
        self.assertIn("except DatabaseError", role_view)
        self.assertIn("Active role lookup failed", role_view)
        self.assertIn("is_deleted=false", role_view)
