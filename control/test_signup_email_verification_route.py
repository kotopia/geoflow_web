from base64 import urlsafe_b64encode
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.http import HttpResponse
from django.test import Client, RequestFactory, SimpleTestCase, override_settings
from django.urls import resolve, reverse

from control import views_signup
from control.services.signup_verification_delivery import (
    build_signup_email_verification_link,
)
from control.services.signup_verification_runtime import (
    load_signup_email_verification_key_ring,
)
from control.services.signup_verification_service import (
    EmailVerificationConfigurationError,
    EmailVerificationRejected,
)


class SignupEmailVerificationRouteTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_route_contains_no_raw_token_path_segment(self):
        route = reverse("signup_verify")

        self.assertEqual(route, "/signup/verify/")
        self.assertIs(
            resolve(route).func,
            views_signup.signup_email_verification_view,
        )
        self.assertNotIn("<str:token>", route)
        self.assertNotIn("<uuid:token>", route)

    @patch.object(views_signup, "render")
    def test_get_renders_fragment_bridge_without_receiving_token(self, render):
        rendered_response = HttpResponse()
        render.return_value = rendered_response
        request = self.factory.get("/signup/verify/#token=browser-only")

        response = views_signup.signup_email_verification_view(request)

        context = render.call_args.args[2]
        self.assertEqual(context, {"auto_submit": True})
        self.assertNotIn("token", context)
        self.assertEqual(response["Referrer-Policy"], "no-referrer")

    @patch.object(views_signup.messages, "success")
    @patch.object(views_signup, "verify_signup_email_from_runtime_config")
    def test_post_passes_token_only_to_verification_service(
        self,
        verify,
        success,
    ):
        request = self.factory.post(
            "/signup/verify/",
            {"token": "opaque-test-token"},
        )
        request._dont_enforce_csrf_checks = True

        response = views_signup.signup_email_verification_view(request)

        verify.assert_called_once_with("opaque-test-token")
        success.assert_called_once()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("login"))

    @override_settings(SESSION_ENGINE="django.contrib.sessions.backends.signed_cookies")
    @patch.object(
        views_signup,
        "verify_signup_email_from_runtime_config",
        side_effect=EmailVerificationRejected(),
    )
    def test_only_verification_post_is_exempt_from_csrf(self, verify):
        client = Client(enforce_csrf_checks=True)

        verify_response = client.post(
            reverse("signup_verify"),
            {"token": "opaque-test-token"},
        )

        self.assertEqual(verify_response.status_code, 400)
        verify.assert_called_once_with("opaque-test-token")

        for route_name in ("signup", "signup_resend"):
            with self.subTest(route_name=route_name):
                response = client.post(reverse(route_name), {})
                self.assertEqual(response.status_code, 403)

    @patch.object(views_signup, "render")
    @patch.object(
        views_signup,
        "verify_signup_email_from_runtime_config",
        side_effect=EmailVerificationRejected(),
    )
    def test_invalid_expired_and_replayed_tokens_share_generic_response(
        self,
        verify,
        render,
    ):
        render.return_value = HttpResponse(status=400)
        request = self.factory.post(
            "/signup/verify/",
            {"token": "opaque-test-token"},
        )
        request._dont_enforce_csrf_checks = True

        views_signup.signup_email_verification_view(request)

        context = render.call_args.args[2]
        self.assertEqual(context, {"verification_failed": True})
        self.assertNotIn("opaque-test-token", repr(render.call_args))
        self.assertEqual(render.call_args.kwargs["status"], 400)
        verify.assert_called_once_with("opaque-test-token")

    def test_bridge_template_runs_without_shared_javascript_before_fragment_cleanup(self):
        template_path = (
            Path(settings.BASE_DIR)
            / "control/templates/control/signup_email_verification.html"
        )
        source = template_path.read_text(encoding="utf-8")

        self.assertNotIn("{% extends", source)
        self.assertNotIn("<script src=", source)
        self.assertIn("window.history.replaceState", source)
        self.assertLess(
            source.index("window.history.replaceState"),
            source.index("form.submit()"),
        )


class SignupEmailVerificationRuntimeTests(SimpleTestCase):
    def test_key_ring_loads_base64_keys_without_exposing_material(self):
        raw_key = b"k" * 32
        settings_obj = SimpleNamespace(
            SIGNUP_EMAIL_VERIFICATION_ACTIVE_KEY_ID="current",
            SIGNUP_EMAIL_VERIFICATION_HMAC_KEYS={
                "current": urlsafe_b64encode(raw_key).decode("ascii"),
            },
        )

        key_ring = load_signup_email_verification_key_ring(
            settings_obj=settings_obj,
        )

        self.assertEqual(key_ring.active_key_id, "current")
        self.assertEqual(key_ring.active_key(), raw_key)

    def test_missing_or_invalid_key_configuration_fails_closed(self):
        configurations = (
            SimpleNamespace(),
            SimpleNamespace(
                SIGNUP_EMAIL_VERIFICATION_ACTIVE_KEY_ID="current",
                SIGNUP_EMAIL_VERIFICATION_HMAC_KEYS={"current": "not-base64!"},
            ),
        )
        for settings_obj in configurations:
            with self.subTest(settings_obj=settings_obj):
                with self.assertRaises(EmailVerificationConfigurationError) as caught:
                    load_signup_email_verification_key_ring(
                        settings_obj=settings_obj,
                    )
                self.assertNotIn("not-base64", str(caught.exception))


class SignupEmailVerificationDeliveryTests(SimpleTestCase):
    def test_link_places_token_in_fragment_not_path_or_query(self):
        token = "v1.current." + ("s" * 43)

        link = build_signup_email_verification_link(
            "https://example.invalid/signup/verify/",
            token,
        )

        before_fragment, fragment = link.split("#", 1)
        self.assertEqual(
            before_fragment,
            "https://example.invalid/signup/verify/",
        )
        self.assertIn("token=", fragment)
        self.assertNotIn(token, before_fragment)
