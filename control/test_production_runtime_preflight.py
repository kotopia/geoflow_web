from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from control.services.production_runtime_preflight import (
    CANONICAL_PRODUCTION_ORIGIN,
    inspect_production_runtime_preflight,
)


class ProductionRuntimePreflightTests(SimpleTestCase):
    def _settings(self, **overrides):
        values = {
            "DEBUG": False,
            "ALLOWED_HOSTS": ["geoflow.co.kr"],
            "CSRF_COOKIE_SECURE": True,
            "SESSION_COOKIE_SECURE": True,
            "SITE_ORIGIN": "http://192.168.0.19:8000",
            "SIGNUP_TERMS_URL": "",
            "SIGNUP_PRIVACY_URL": "",
            "SIGNUP_LEGAL_DOCUMENTS_CONFIRMED": None,
            "SECURE_SSL_REDIRECT": False,
            "SECURE_HSTS_SECONDS": 0,
            "SECURE_PROXY_SSL_HEADER": None,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    @patch(
        "control.services.production_runtime_preflight.signup_public_runtime_ready",
        return_value=True,
    )
    def test_environment_can_make_local_placeholders_production_ready(
        self,
        runtime_ready,
    ):
        result = inspect_production_runtime_preflight(
            settings_obj=self._settings(),
            environ={
                "SITE_ORIGIN": CANONICAL_PRODUCTION_ORIGIN,
                "SIGNUP_TERMS_URL": f"{CANONICAL_PRODUCTION_ORIGIN}/terms/",
                "SIGNUP_PRIVACY_URL": f"{CANONICAL_PRODUCTION_ORIGIN}/privacy/",
                "SIGNUP_LEGAL_DOCUMENTS_CONFIRMED": "1",
            },
        )

        self.assertTrue(result.ready)
        self.assertFalse(any(check.status == "FAIL" for check in result.checks))
        runtime_ready.assert_called_once()

    @patch(
        "control.services.production_runtime_preflight.signup_public_runtime_ready",
        return_value=False,
    )
    def test_failures_are_named_without_echoing_secret_values(self, runtime_ready):
        secret = "DO_NOT_PRINT_THIS_SECRET"
        result = inspect_production_runtime_preflight(
            settings_obj=self._settings(
                DEBUG=True,
                ALLOWED_HOSTS=["*"],
                CSRF_COOKIE_SECURE=False,
                SESSION_COOKIE_SECURE=False,
                EMAIL_HOST_PASSWORD=secret,
            ),
            environ={
                "SITE_ORIGIN": "http://invalid.local",
                "DEFAULT_FROM_EMAIL": "noreply@geoflow.local",
                "SOME_SECRET": secret,
            },
        )

        self.assertFalse(result.ready)
        rendered = "\n".join(
            f"{check.status}:{check.code}:{check.message}"
            for check in result.checks
        )
        self.assertNotIn(secret, rendered)
        self.assertIn("FAIL:debug_disabled", rendered)
        self.assertIn("FAIL:signup_runtime", rendered)

    @patch(
        "control.services.production_runtime_preflight.signup_public_runtime_ready",
        return_value=True,
    )
    def test_https_proxy_controls_are_warnings_before_live_validation(
        self,
        runtime_ready,
    ):
        result = inspect_production_runtime_preflight(
            settings_obj=self._settings(),
            environ={
                "SITE_ORIGIN": CANONICAL_PRODUCTION_ORIGIN,
                "SIGNUP_TERMS_URL": f"{CANONICAL_PRODUCTION_ORIGIN}/terms/",
                "SIGNUP_PRIVACY_URL": f"{CANONICAL_PRODUCTION_ORIGIN}/privacy/",
                "SIGNUP_LEGAL_DOCUMENTS_CONFIRMED": "true",
            },
        )

        warning_codes = {
            check.code for check in result.checks if check.status == "WARN"
        }
        self.assertEqual(
            warning_codes,
            {"ssl_redirect", "hsts", "proxy_ssl_header"},
        )
        self.assertTrue(result.ready)
