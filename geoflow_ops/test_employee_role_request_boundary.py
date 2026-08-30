from pathlib import Path
from unittest import TestCase


OPS_DIR = Path(__file__).resolve().parent
CONTROL_SERVICES = OPS_DIR.parent / "control" / "services"


class EmployeeRoleRequestCentralAccountBoundaryTests(TestCase):
    def test_live_role_request_view_never_calls_identity_provisioning_helpers(self):
        source = (OPS_DIR / "views_employee_role_request.py").read_text(encoding="utf-8")
        self.assertIn("lookup_user_id_from_request", source)
        self.assertIn("queue_tenant_role_request", source)
        self.assertNotIn("get_or_create_user_by_email", source)
        self.assertNotIn("create_user", source)
        self.assertNotIn("add_or_update_join_request", source)

    def test_live_route_uses_safe_role_request_view_not_legacy_view_directly(self):
        urls = (OPS_DIR / "urls.py").read_text(encoding="utf-8")
        security_view = (OPS_DIR / "employee_security_views.py").read_text(encoding="utf-8")
        self.assertIn("employee_security_views.employee_role_request", urls)
        self.assertIn("views_employee_role_request.employees_request_role_safe", security_view)
        self.assertNotIn(
            'views_employees.employees_request_role, name="employees_request_role"',
            urls,
        )

    def test_central_service_rejects_reserved_system_role_codes(self):
        source = (CONTROL_SERVICES / "tenant_role_request_service.py").read_text(
            encoding="utf-8"
        )
        for reserved in ("central_admin", "system_admin", "super_admin", "owner"):
            self.assertIn(reserved, source)
        self.assertIn("_FORBIDDEN_ROLE_PREFIXES", source)

    def test_central_role_request_service_rechecks_active_identity_group_and_role(self):
        source = (CONTROL_SERVICES / "tenant_role_request_service.py").read_text(
            encoding="utf-8"
        )
        for required in (
            "requester.is_active=TRUE",
            "requester.email_verified=TRUE",
            "requester.password_hash IS NOT NULL",
            "COALESCE(active_group.status",
            "requested_role.code=%s",
            "role_status_clause",
            "FOR KEY SHARE OF requester, active_group, requested_role",
            "ON CONFLICT (user_id, group_id, requested_email)",
            "decided_at=NULL",
            "decided_by=NULL",
        ):
            self.assertIn(required, source)
        for forbidden in (
            "INSERT INTO users",
            "UPDATE users",
            "get_or_create_user_by_email",
        ):
            self.assertNotIn(forbidden, source)

    def test_role_status_is_enforced_when_schema_provides_it(self):
        source = (CONTROL_SERVICES / "tenant_role_request_service.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('_column_exists(cursor, "roles", "status")', source)
        self.assertIn("requested_role.status", source)

    def test_password_hash_like_wildcards_are_escaped_for_parameterized_sql(self):
        source = (CONTROL_SERVICES / "tenant_role_request_service.py").read_text(
            encoding="utf-8"
        )
        for pattern in (
            "pbkdf2_sha256$%%",
            "bcrypt_sha256$%%",
            "$2a$%%",
            "$2b$%%",
            "$2y$%%",
        ):
            self.assertIn(f"LIKE '{pattern}'", source)
        self.assertEqual(source.count("requester.password_hash LIKE"), 5)
