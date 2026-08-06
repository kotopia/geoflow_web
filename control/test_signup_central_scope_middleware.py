from types import SimpleNamespace

from django.test import SimpleTestCase, override_settings

from control.middleware import (
    CentralAccountActiveGuardMiddleware,
    CentralGuardMiddleware,
    TenantMembershipFreshnessGuardMiddleware,
    TenantMiddleware,
    current_db_alias,
)


@override_settings(CENTRAL_DB_ALIAS="central")
class SignupCentralScopeMiddlewareTests(SimpleTestCase):
    def test_signup_verification_is_public_to_active_account_guard(self):
        self.assertTrue(
            CentralAccountActiveGuardMiddleware._is_public_path(
                "/signup/verify/"
            )
        )

    def test_signup_verification_is_exempt_from_tenant_freshness_guard(self):
        self.assertTrue(
            TenantMembershipFreshnessGuardMiddleware._is_exempt_path(
                "/signup/verify/"
            )
        )

    def test_tenant_middleware_uses_central_request_scope_for_signup_path(self):
        response = object()
        middleware = TenantMiddleware(lambda _request: response)
        request = SimpleNamespace(
            path="/signup/verify/",
            session={
                "tenant_db_alias": "tenant-existing-session",
                "group_id": "group-reference",
            },
        )

        result = middleware(request)

        self.assertIs(result, response)
        self.assertEqual(request.session["scope"], "central")
        self.assertEqual(current_db_alias(), "central")
        self.assertEqual(
            request.session["tenant_db_alias"],
            "tenant-existing-session",
        )

    def test_central_guard_does_not_redirect_signup_verification(self):
        middleware = CentralGuardMiddleware(lambda request: request)
        request = SimpleNamespace(
            path="/signup/verify/",
            session={"tenant_db_alias": "central"},
        )

        self.assertIsNone(middleware.process_request(request))

    def test_scope_rules_cover_signup_form_and_verification_route(self):
        for path in ("/signup/", "/signup/verify/"):
            with self.subTest(path=path):
                self.assertTrue(
                    CentralAccountActiveGuardMiddleware._is_public_path(path)
                )
                self.assertTrue(
                    TenantMembershipFreshnessGuardMiddleware._is_exempt_path(path)
                )
