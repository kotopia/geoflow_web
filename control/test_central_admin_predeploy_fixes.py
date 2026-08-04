from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse

from control import views_groups_admin, views_users_admin
from control.services import central_repo


class _QueryCursor:
    def __init__(self, handler):
        self.handler = handler
        self.fetchone_result = None
        self.fetchall_result = []
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        self.executed.append((normalized, params or []))
        self.fetchone_result, self.fetchall_result = self.handler(normalized, params or [])

    def fetchone(self):
        return self.fetchone_result

    def fetchall(self):
        return self.fetchall_result


class _Connection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


class CentralAdminPredeployFixTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_user_detail_context_supplies_assignment_and_display_rows(self):
        def handler(sql, params):
            if "FROM users u" in sql:
                return (
                    ("user-key", "masked@example.invalid", True, True, None, None, None),
                    [],
                )
            if "FROM user_group_map ugm" in sql:
                return (None, [("group-key", "Group", "group-code", "role-code", "Role", "active")])
            if "FROM join_requests jr" in sql:
                return (None, [("request-key", "Group", "role-code", "pending", None)])
            if "FROM groups g" in sql and "COALESCE(g.status" in sql:
                return (None, [("group-key", "Group", "group-code")])
            if "FROM roles r" in sql:
                return (None, [("role-key", "role-code")])
            raise AssertionError("Unexpected central admin query")

        cursor = _QueryCursor(handler)
        captured = {}

        def fake_render(request, template_name, context):
            captured.update(context)
            return HttpResponse("ok")

        request = self.factory.get("/control/mgmt/users/detail/")
        with patch.object(views_users_admin, "connections", {"default": _Connection(cursor)}), patch.object(
            views_users_admin, "render", side_effect=fake_render
        ):
            response = views_users_admin.users_detail_admin.__wrapped__(request, "user-key")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured["groups"][0]["id"], "group-key")
        self.assertEqual(captured["roles"][0]["id"], "role-key")
        self.assertEqual(captured["memberships"][0]["group_code"], "group-code")
        self.assertEqual(captured["memberships"][0]["status"], "active")
        self.assertEqual(captured["joins"], captured["requests"])

    def test_existing_assignment_upsert_contract_is_preserved(self):
        def handler(sql, params):
            return (None, [])

        cursor = _QueryCursor(handler)
        request = self.factory.post(
            "/control/mgmt/users/assign/",
            {"group_id": "group-key", "role_id": "role-key"},
        )
        user_key = UUID(int=1)

        with patch.object(views_users_admin, "connections", {"default": _Connection(cursor)}), patch.object(
            views_users_admin.messages, "success"
        ):
            response = views_users_admin.users_assign_group_admin.__wrapped__(request, user_key)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(cursor.executed), 1)
        self.assertIn("ON CONFLICT (user_id, group_id)", cursor.executed[0][0])
        self.assertEqual(cursor.executed[0][1], [user_key, "group-key", "role-key"])

    def test_group_list_uses_distinct_metadata_aliases_and_deleted_flag(self):
        def handler(sql, params):
            if "ORDER BY g.created_at" in sql:
                return (
                    None,
                    [
                        ("group-a", "code-a", "Group A", "active", None, None),
                        ("group-b", "code-b", "Group B", "inactive", None, None),
                    ],
                )
            if "FROM group_db_config" in sql:
                return (None, [("group-a", "metadata-a"), ("group-b", "metadata-b")])
            if "WHERE deleted_at IS NOT NULL" in sql:
                return (None, [("group-b",)])
            raise AssertionError("Unexpected group-list query")

        cursor = _QueryCursor(handler)

        def column_exists(alias, table, column):
            return column in {"owner_user_id", "deleted_at"}

        with patch.object(central_repo, "connections", {"default": _Connection(cursor)}), patch.object(
            central_repo, "_central_alias", return_value="default"
        ), patch.object(central_repo, "_table_exists", return_value=True), patch.object(
            central_repo, "_column_exists", side_effect=column_exists
        ):
            rows = central_repo.list_groups_admin()

        self.assertEqual(rows[0][6], "metadata-a")
        self.assertEqual(rows[1][6], "metadata-b")
        self.assertNotEqual(rows[0][6], rows[1][6])
        self.assertFalse(rows[0][7])
        self.assertTrue(rows[1][7])

    def test_group_edit_reads_alias_from_central_metadata(self):
        def handler(sql, params):
            self.assertIn("LEFT JOIN group_db_config", sql)
            return (("group-key", "code", "Group", "active", "", None, "metadata-a"), [])

        cursor = _QueryCursor(handler)
        captured = {}

        def fake_render(request, template_name, context):
            captured.update(context)
            return HttpResponse("ok")

        request = self.factory.get("/control/central/groups/edit/")
        with patch.object(views_groups_admin.C, "_table_exists", return_value=True), patch.object(
            views_groups_admin, "connections", {"default": _Connection(cursor)}
        ), patch.object(views_groups_admin, "render", side_effect=fake_render):
            response = views_groups_admin.group_edit_admin.__wrapped__(request, "group-key")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured["row"][6], "metadata-a")

    def test_alias_field_is_read_only_and_destructive_actions_are_absent(self):
        template_dir = Path(__file__).resolve().parent / "templates" / "control"
        group_form = (template_dir / "group_form_admin.html").read_text(encoding="utf-8")
        group_list = (template_dir / "group_list_admin.html").read_text(encoding="utf-8")

        self.assertIn('readonly aria-readonly="true"', group_form)
        self.assertNotIn('name="db_alias"', group_form)
        self.assertIn("is_deleted", group_list)
        for forbidden_name in (
            "tenant_drop_admin",
            "tenant_detach_admin",
            "tenant_schema_version_audit_admin",
            "tenant_validate_admin",
            "tenant_provision_plan_admin",
            "users_membership_delete_admin",
            "users_membership_deactivate_admin",
        ):
            self.assertNotIn(forbidden_name, group_form)
            self.assertNotIn(forbidden_name, group_list)

    def test_existing_central_admin_url_names_resolve(self):
        self.assertEqual(reverse("control:group_list_admin"), "/control/central/groups/")
        self.assertIn("/assign/", reverse("control:users_assign_group_admin", args=[UUID(int=1)]))
