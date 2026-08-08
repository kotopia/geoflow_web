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
        self.assertIn("pbkdf2_sha256$%", source)
        self.assertIn("lower(COALESCE(g.status, ''))='active'", source)
        self.assertIn("RETURNING id", source)
        self.assertNotIn("get_or_create_user_by_email", source)

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
