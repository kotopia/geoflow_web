from contextlib import nullcontext
from datetime import timedelta
from uuid import UUID
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase
from django.urls import resolve, reverse
from django.utils import timezone

from control import urls as control_urls
from control import views_auth
from control import views_users_admin


class _RecordingCursor:
    def __init__(self):
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.executed.append((" ".join(sql.split()), params or []))

    def fetchone(self):
        return (
            "user-key",
            "masked@example.invalid",
            timezone.now() + timedelta(hours=1),
            False,
        )


class _Connection:
    def __init__(self, cursor):
        self.cursor_instance = cursor

    def cursor(self):
        return self.cursor_instance


class PasswordSetupRouteAlignmentTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_uuid_password_route_resolves_to_canonical_view(self):
        route = reverse("control:set_password", args=[UUID(int=1)])

        self.assertIs(resolve(route).func, views_users_admin.set_password_view)

    def test_string_password_route_resolves_to_canonical_view(self):
        route = reverse("control:account_set_password", args=["token-value"])

        self.assertIs(resolve(route).func, views_users_admin.set_password_view)

    def test_url_module_uses_explicit_canonical_alias(self):
        self.assertIs(
            control_urls.admin_set_password_view,
            views_users_admin.set_password_view,
        )
        self.assertFalse(hasattr(control_urls, "set_password_view"))

    def test_dormant_auth_password_setup_view_is_absent(self):
        self.assertFalse(hasattr(views_auth, "set_password_view"))

    def test_success_updates_password_and_verification_without_activation(self):
        cursor = _RecordingCursor()
        request = self.factory.post(
            "/control/account/set-password/token-value/",
            {"password": "valid-password", "password2": "valid-password"},
        )
        request._dont_enforce_csrf_checks = True

        with (
            patch.object(
                views_users_admin,
                "connections",
                {"default": _Connection(cursor)},
            ),
            patch.object(
                views_users_admin.transaction,
                "atomic",
                return_value=nullcontext(),
            ),
            patch.object(
                views_users_admin,
                "make_password",
                return_value="password-hash",
            ),
            patch.object(views_users_admin.messages, "success") as success,
        ):
            response = views_users_admin.set_password_view(
                request,
                "token-value",
            )

        statements = [sql for sql, _ in cursor.executed]
        user_updates = [sql for sql in statements if sql.startswith("UPDATE users")]

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("login"))
        self.assertEqual(len(user_updates), 1)
        self.assertIn("password_hash=%s", user_updates[0])
        self.assertIn("email_verified=TRUE", user_updates[0])
        self.assertNotIn("is_active", user_updates[0])
        self.assertTrue(
            any(sql.startswith("UPDATE password_reset_tokens") for sql in statements)
        )

        message = success.call_args.args[1]
        self.assertIn("비밀번호가 설정되었습니다.", message)
        self.assertIn("활성 상태인 경우", message)
        self.assertIn("관리자 승인 후", message)
        self.assertNotIn("이제 로그인할 수 있습니다", message)
