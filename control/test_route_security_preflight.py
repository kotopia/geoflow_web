from django.test import SimpleTestCase

from control.services.route_security_preflight import (
    ROUTE_SECURITY_BOUNDARIES,
    inspect_route_security_boundaries,
)


class RouteSecurityPreflightTests(SimpleTestCase):
    def test_reviewed_sensitive_routes_keep_expected_boundaries(self):
        checks = inspect_route_security_boundaries()
        self.assertEqual(len(checks), len(ROUTE_SECURITY_BOUNDARIES))
        failures = [check.code for check in checks if not check.ready]
        self.assertEqual(failures, [])
