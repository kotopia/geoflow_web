from inspect import getsource

from django.test import SimpleTestCase

from control.views_login_security import login_view


class LoginBridgeSecurityTests(SimpleTestCase):
    def test_login_wrapper_deprivileges_django_session_bridge(self):
        source = getsource(login_view)
        self.assertIn('@sensitive_post_parameters("email", "username", "password")', source)
        self.assertIn("@never_cache", source)
        self.assertIn("is_active=True", source)
        self.assertIn("is_staff=False", source)
        self.assertIn("is_superuser=False", source)
        self.assertIn("logout(request)", source)
