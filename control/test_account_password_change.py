from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import RequestFactory, SimpleTestCase
from django.urls import resolve, reverse

from control.services.central_password_change_service import (
    CentralPasswordChangeAuthenticationError,
    CentralPasswordChangeValidationError,
    _validate_password_change,
)
from control.views_account_security import account_password_change_view


ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "control" / "services" / "central_password_change_service.py"
VIEW = ROOT / "control" / "views_account_security.py"
TEMPLATE = ROOT / "control" / "templates" / "control" / "account_password_change.html"
CENTRAL_TOPBAR = ROOT / "control" / "templates" / "control" / "partials" / "topbar.html"
TENANT_TOPBAR = ROOT / "geoflow_ops" / "templates" / "geoflow_ops" / "partials" / "topbar.html"


class AccountPasswordChangeValidationTests(SimpleTestCase):
    @patch("control.services.central_password_change_service.validate_password")
    @patch("control.services.central_password_change_service.verify_central_login_password")
    def test_valid_change_rechecks_current_and_reuse_then_runs_validator(self, verify, validator):
        verify.side_effect = [SimpleNamespace(valid=True), SimpleNamespace(valid=False)]

        _validate_password_change(
            email="user@example.com",
            encoded_password="encoded",
            current_password="current-secret",
            new_password="new-secret-12345",
        )

        self.assertEqual(verify.call_count, 2)
        self.assertEqual(verify.call_args_list[0].args, ("current-secret", "encoded"))
        self.assertEqual(verify.call_args_list[1].args, ("new-secret-12345", "encoded"))
        validator.assert_called_once()

    @patch("control.services.central_password_change_service.verify_central_login_password")
    def test_wrong_current_password_is_rejected(self, verify):
        verify.return_value = SimpleNamespace(valid=False)
        with self.assertRaises(CentralPasswordChangeAuthenticationError):
            _validate_password_change(
                email="user@example.com",
                encoded_password="encoded",
                current_password="wrong-secret",
                new_password="new-secret-12345",
            )

    @patch("control.services.central_password_change_service.verify_central_login_password")
    def test_reusing_current_password_is_rejected(self, verify):
        verify.side_effect = [SimpleNamespace(valid=True), SimpleNamespace(valid=True)]
        with self.assertRaises(CentralPasswordChangeValidationError):
            _validate_password_change(
                email="user@example.com",
                encoded_password="encoded",
                current_password="same-secret",
                new_password="same-secret",
            )

    @patch("control.services.central_password_change_service.validate_password")
    @patch("control.services.central_password_change_service.verify_central_login_password")
    def test_django_password_policy_rejection_is_sanitized(self, verify, validator):
        verify.side_effect = [SimpleNamespace(valid=True), SimpleNamespace(valid=False)]
        validator.side_effect = ValidationError("raw validator detail")
        with self.assertRaisesRegex(CentralPasswordChangeValidationError, "password policy rejected") as ctx:
            _validate_password_change(
                email="user@example.com",
                encoded_password="encoded",
                current_password="current-secret",
                new_password="weak",
            )
        self.assertNotIn("raw validator detail", str(ctx.exception))


class AccountPasswordChangeRouteSecurityTests(SimpleTestCase):
    def test_route_resolves_to_authenticated_password_change_view(self):
        url = reverse("control:account_password_change")
        self.assertEqual(url, "/control/account/password/change/")
        self.assertEqual(resolve(url).func, account_password_change_view)

    def test_anonymous_get_redirects_to_login(self):
        request = RequestFactory().get(reverse("control:account_password_change"))
        request.user = SimpleNamespace(is_authenticated=False)
        response = account_password_change_view(request)
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_authenticated_post_without_csrf_is_forbidden_before_service(self):
        request = RequestFactory().post(
            reverse("control:account_password_change"),
            data={
                "current_password": "current-secret",
                "new_password": "new-secret-12345",
                "new_password2": "new-secret-12345",
            },
        )
        request.user = SimpleNamespace(is_authenticated=True)
        response = account_password_change_view(request)
        self.assertEqual(response.status_code, 403)


class AccountPasswordChangeContractTests(SimpleTestCase):
    def test_service_locks_active_verified_account_and_rotates_security_state(self):
        text = SERVICE.read_text(encoding="utf-8")
        self.assertIn("FOR UPDATE", text)
        self.assertIn("is_active=TRUE", text)
        self.assertIn("email_verified=TRUE", text)
        self.assertIn("make_password(new_password)", text)
        self.assertIn("UPDATE account_password_reset_tokens", text)
        self.assertIn("SET revoked_at=now()", text)
        self.assertIn("purpose='account_password_reset'", text)
        self.assertIn("consumed_at IS NULL", text)
        self.assertIn("revoked_at IS NULL", text)
        self.assertIn("UPDATE password_reset_tokens", text)
        self.assertIn("SET used=TRUE", text)
        self.assertIn("bridge_user.set_unusable_password()", text)
        self.assertIn("transaction.atomic(using=central_alias)", text)

    def test_view_does_not_keep_session_after_success(self):
        text = VIEW.read_text(encoding="utf-8")
        self.assertIn('@sensitive_post_parameters("current_password", "new_password", "new_password2")', text)
        self.assertIn("@login_required", text)
        self.assertIn("@csrf_protect", text)
        self.assertIn("logout(request)", text)
        self.assertNotIn("messages.error(request, str(", text)

    def test_form_uses_password_autocomplete_and_never_echoes_values(self):
        text = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("{% csrf_token %}", text)
        self.assertIn('autocomplete="current-password"', text)
        self.assertGreaterEqual(text.count('autocomplete="new-password"'), 2)
        self.assertNotIn('value="{{', text)

    def test_both_central_and_tenant_topbars_link_to_password_change(self):
        marker = "control:account_password_change"
        self.assertIn(marker, CENTRAL_TOPBAR.read_text(encoding="utf-8"))
        self.assertIn(marker, TENANT_TOPBAR.read_text(encoding="utf-8"))
