from inspect import getsource

from django.test import SimpleTestCase

from control.views_legacy_password_security import legacy_password_setup_view


class LegacyPasswordReferrerBoundaryTests(SimpleTestCase):
    def test_legacy_password_wrapper_suppresses_referrer_and_cache(self):
        source = getsource(legacy_password_setup_view)
        self.assertIn('@sensitive_variables("token")', source)
        self.assertIn("@never_cache", source)
        self.assertIn('response["Referrer-Policy"] = "no-referrer"', source)
        self.assertIn('response["Cache-Control"]', source)
