from types import SimpleNamespace

from django.test import SimpleTestCase

from control.services.session_security_preflight import (
    inspect_session_security_baseline,
)


class SessionSecurityBaselineTests(SimpleTestCase):
    def test_safe_cookie_policy_passes(self):
        checks = inspect_session_security_baseline(
            settings_obj=SimpleNamespace(
                SESSION_COOKIE_HTTPONLY=True,
                SESSION_COOKIE_SAMESITE="Lax",
                CSRF_COOKIE_SAMESITE="Strict",
            )
        )
        self.assertTrue(all(check.ready for check in checks))

    def test_cross_site_or_script_readable_session_policy_fails(self):
        checks = inspect_session_security_baseline(
            settings_obj=SimpleNamespace(
                SESSION_COOKIE_HTTPONLY=False,
                SESSION_COOKIE_SAMESITE=None,
                CSRF_COOKIE_SAMESITE="None",
            )
        )
        failures = {check.code for check in checks if not check.ready}
        self.assertEqual(
            failures,
            {
                "session_cookie_httponly",
                "session_cookie_samesite",
                "csrf_cookie_samesite",
            },
        )
