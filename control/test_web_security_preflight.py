from types import SimpleNamespace

from django.test import SimpleTestCase

from control.services.web_security_preflight import inspect_web_security_baseline


class WebSecurityPreflightTests(SimpleTestCase):
    def _settings(self, **overrides):
        values = {
            "MIDDLEWARE": [
                "django.middleware.security.SecurityMiddleware",
                "django.middleware.csrf.CsrfViewMiddleware",
                "django.middleware.clickjacking.XFrameOptionsMiddleware",
            ],
            "CSRF_TRUSTED_ORIGINS": ["https://geoflow.co.kr"],
            "SECURE_CONTENT_TYPE_NOSNIFF": True,
            "SECURE_REFERRER_POLICY": "same-origin",
            "X_FRAME_OPTIONS": "DENY",
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_safe_browser_security_policy_passes(self):
        checks = inspect_web_security_baseline(settings_obj=self._settings())
        self.assertTrue(all(check.ready for check in checks))

    def test_missing_origin_or_weakened_headers_fail(self):
        checks = inspect_web_security_baseline(
            settings_obj=self._settings(
                CSRF_TRUSTED_ORIGINS=[],
                SECURE_CONTENT_TYPE_NOSNIFF=False,
                SECURE_REFERRER_POLICY="unsafe-url",
                X_FRAME_OPTIONS="ALLOWALL",
            )
        )
        failures = {check.code for check in checks if not check.ready}
        self.assertEqual(
            failures,
            {
                "csrf_canonical_origin",
                "content_type_nosniff",
                "referrer_policy",
                "frame_options",
            },
        )
