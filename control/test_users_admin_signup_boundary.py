from contextlib import nullcontext
from inspect import unwrap
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from django.test import RequestFactory, SimpleTestCase

from control import views_users_admin
from control.services.central_account_erasure_service import (
    AccountErasureError,
    AccountErasureResult,
)


CONTROL_DIR = Path(__file__).resolve().parent


class _RoleAssignmentCursor:
    def __init__(self, fetch_results):
        self.fetch_results = list(fetch_results)
        self.executions = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.executions.append((sql, list(params or [])))

    def fetchone(self):
        if not self.fetch_results:
            return None
        return self.fetch_results.pop(0)


class _RoleAssignmentConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


class UsersAdminSignupBoundaryTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_delete_view_delegates_to_erasure_service_without_echoing_email(self):
        request = self.factory.post("/control/mgmt/users/delete/")
        target = UUID(int=11)

        with patch.object(
            views_users_admin,
            "erase_central_account_personal_data",
            return_value=AccountErasureResult(mode="deleted"),
        ) as erase, patch.object(
            views_users_admin.messages,
            "success",
        ) as success:
            response = unwrap(views_users_admin.users_delete_admin)(request, target)

        self.assertEqual(response.status_code, 302)
        erase.assert_called_once_with(str(target))
        success.assert_called_once_with(
            request,
            "사용자 계정 개인정보가 삭제되었습니다.",
        )

    def test_delete_view_reports_anonymized_result_without_identifier(self):
        request = self.factory.post("/control/mgmt/users/delete/")
        with patch.object(
            views_users_admin,
            "erase_central_account_personal_data",
            return_value=AccountErasureResult(mode="anonymized"),
        ), patch.object(views_users_admin.messages, "success") as success:
            response = unwrap(views_users_admin.users_delete_admin)(
                request,
                UUID(int=12),
            )

        self.assertEqual(response.status_code, 302)
        message = success.call_args.args[1]
        self.assertIn("익명화", message)
        self.assertNotIn("@", message)

    def test_delete_view_fails_closed_on_erasure_error(self):
        request = self.factory.post("/control/mgmt/users/delete/")
        with patch.object(
            views_users_admin,
            "erase_central_account_personal_data",
            side_effect=AccountErasureError("blocked"),
        ), patch.object(views_users_admin.messages, "error") as error:
            response = unwrap(views_users_admin.users_delete_admin)(
                request,
                UUID(int=13),
            )

        self.assertEqual(response.status_code, 302)
        error.assert_called_once()

    def test_users_admin_source_has_no_legacy_direct_account_delete_chain(self):
        source = (CONTROL_DIR / "views_users_admin.py").read_text(encoding="utf-8")
        self.assertIn("erase_central_account_personal_data", source)
        for forbidden in (
            "DELETE FROM users WHERE",
            "DELETE FROM signup_requests",
            "DELETE FROM signup_request_events",
            "DELETE FROM signup_email_verification_tokens",
            "DELETE FROM signup_verification_delivery_outbox",
        ):
            self.assertNotIn(forbidden, source)

    def test_manual_assignment_cannot_bypass_account_activation(self):
        source = (CONTROL_DIR / "views_users_admin.py").read_text(encoding="utf-8")
        self.assertIn("u.is_active=TRUE", source)
        self.assertIn("u.email_verified=TRUE", source)
        self.assertIn("u.password_hash IS NOT NULL", source)
        self.assertIn("pbkdf2_sha256$%%", source)
        self.assertIn("lower(COALESCE(g.status, ''))='active'", source)
        self.assertIn("FOR UPDATE OF u", source)
        self.assertIn("RETURNING id", source)
        self.assertNotIn("get_or_create_user_by_email", source)

    def test_manual_assignment_does_not_require_legacy_unique_constraint_or_pgcrypto(self):
        source = (CONTROL_DIR / "views_users_admin.py").read_text(encoding="utf-8")
        assignment_source = source.split("def users_assign_group_admin", 1)[1]
        self.assertNotIn("ON CONFLICT", assignment_source)
        self.assertNotIn("gen_random_uuid()", assignment_source)
        self.assertIn("UPDATE user_group_map", assignment_source)
        self.assertIn("INSERT INTO user_group_map", assignment_source)
        self.assertIn("str(uuid4())", assignment_source)

    def test_manual_assignment_inserts_when_membership_does_not_exist(self):
        request = self.factory.post(
            "/control/mgmt/users/assign/",
            {"group_id": "group-1", "role_id": "role-1"},
        )
        cursor = _RoleAssignmentCursor(
            [("eligible-user",), None, ("new-membership",)]
        )
        connection = _RoleAssignmentConnection(cursor)

        with patch.object(
            views_users_admin,
            "connections",
            {"default": connection},
        ), patch.object(
            views_users_admin.transaction,
            "atomic",
            return_value=nullcontext(),
        ), patch.object(views_users_admin.messages, "success") as success:
            response = unwrap(views_users_admin.users_assign_group_admin)(
                request,
                UUID(int=31),
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(cursor.executions), 3)
        self.assertIn("FOR UPDATE OF u", cursor.executions[0][0])
        self.assertIn("UPDATE user_group_map", cursor.executions[1][0])
        self.assertIn("INSERT INTO user_group_map", cursor.executions[2][0])
        success.assert_called_once()

    def test_manual_assignment_updates_existing_membership_without_insert(self):
        request = self.factory.post(
            "/control/mgmt/users/assign/",
            {"group_id": "group-1", "role_id": "role-2"},
        )
        cursor = _RoleAssignmentCursor(
            [("eligible-user",), ("existing-membership",)]
        )
        connection = _RoleAssignmentConnection(cursor)

        with patch.object(
            views_users_admin,
            "connections",
            {"default": connection},
        ), patch.object(
            views_users_admin.transaction,
            "atomic",
            return_value=nullcontext(),
        ), patch.object(views_users_admin.messages, "success"):
            response = unwrap(views_users_admin.users_assign_group_admin)(
                request,
                UUID(int=32),
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(cursor.executions), 2)
        self.assertIn("UPDATE user_group_map", cursor.executions[1][0])
        self.assertNotIn(
            "INSERT INTO user_group_map",
            "\n".join(sql for sql, _ in cursor.executions),
        )

    def test_manual_assignment_fails_closed_when_account_is_ineligible(self):
        request = self.factory.post(
            "/control/mgmt/users/assign/",
            {"group_id": "group-1", "role_id": "role-1"},
        )
        cursor = _RoleAssignmentCursor([None])
        connection = _RoleAssignmentConnection(cursor)

        with patch.object(
            views_users_admin,
            "connections",
            {"default": connection},
        ), patch.object(
            views_users_admin.transaction,
            "atomic",
            return_value=nullcontext(),
        ), patch.object(views_users_admin.messages, "error") as error:
            response = unwrap(views_users_admin.users_assign_group_admin)(
                request,
                UUID(int=33),
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(cursor.executions), 1)
        self.assertIn("유효한 그룹/역할", error.call_args.args[1])

    def test_join_request_detail_supports_both_schema_generations(self):
        source = (CONTROL_DIR / "views_users_admin.py").read_text(encoding="utf-8")
        self.assertIn('("requested_email", "email")', source)
        self.assertIn('"requested_role_code"', source)
        self.assertIn('"role_id"', source)

    def test_users_list_has_one_detail_action_and_explicit_privacy_delete_label(self):
        source = (
            CONTROL_DIR / "templates/control/users_list_admin.html"
        ).read_text(encoding="utf-8")
        self.assertEqual(source.count("control:users_detail_admin"), 1)
        self.assertIn("개인정보 삭제", source)
        self.assertIn("익명화", source)


class UsersAdminSelfErasureBoundaryTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_delete_view_blocks_current_central_admin_self_erasure(self):
        request = self.factory.post("/control/mgmt/users/delete/")
        target = UUID(int=21)
        with patch.object(
            views_users_admin,
            "lookup_user_id_from_request",
            return_value=str(target),
        ), patch.object(
            views_users_admin,
            "erase_central_account_personal_data",
        ) as erase, patch.object(views_users_admin.messages, "error") as error:
            response = unwrap(views_users_admin.users_delete_admin)(request, target)

        self.assertEqual(response.status_code, 302)
        erase.assert_not_called()
        self.assertIn("직접 삭제할 수 없습니다", error.call_args.args[1])
