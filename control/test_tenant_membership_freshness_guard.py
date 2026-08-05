from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import reverse

from control.middleware import TenantMembershipFreshnessGuardMiddleware


class TenantMembershipFreshnessGuardMiddlewareTests(SimpleTestCase):
    TENANT_STATE = {
        "tenant_db_alias": "tenant-key",
        "db_key": "tenant-key",
        "group_id": "group-key",
        "group_uuid": "group-key",
        "tenant_candidates": [{"id": "candidate-key"}],
        "roles": [{"code": "role"}],
        "perms": ["permission"],
        "gf_authz_ctx": {"perms": ["permission"]},
        "gf_roles": ["role"],
        "gf_perms": ["permission"],
    }

    def setUp(self):
        self.factory = RequestFactory()

    def _request(self, path="/contracts/", session=None, **headers):
        request = self.factory.get(path, **headers)
        request.session = dict(self.TENANT_STATE if session is None else session)
        request.user = SimpleNamespace(
            is_authenticated=True,
            email="account@example.invalid",
            username="account@example.invalid",
        )
        return request

    def _call(self, request, membership_row=(1,), lookup_error=None):
        downstream = MagicMock(return_value=MagicMock(status_code=200))
        cursor = MagicMock()
        cursor.fetchone.return_value = membership_row
        if lookup_error is not None:
            cursor.execute.side_effect = lookup_error
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        mocked_connections = MagicMock()
        mocked_connections.__getitem__.return_value = connection

        with patch("control.middleware.connections", mocked_connections):
            response = TenantMembershipFreshnessGuardMiddleware(downstream)(request)

        return response, downstream, cursor, mocked_connections

    @override_settings(CENTRAL_DB_ALIAS="default")
    def test_active_membership_active_group_and_matching_alias_pass(self):
        request = self._request()

        response, downstream, cursor, _ = self._call(request)

        self.assertEqual(response.status_code, 200)
        downstream.assert_called_once_with(request)
        sql, params = cursor.execute.call_args.args
        normalized_sql = " ".join(sql.split())
        self.assertIn("ugm.status = 'active'", normalized_sql)
        self.assertIn("g.status = 'active'", normalized_sql)
        self.assertIn("cfg.db_alias = %s", normalized_sql)
        self.assertEqual(params[1:], ["group-key", "tenant-key"])
        for key in ("roles", "perms", "gf_authz_ctx", "gf_roles", "gf_perms"):
            self.assertNotIn(key, request.session)
        self.assertEqual(request.session["tenant_db_alias"], "tenant-key")
        self.assertEqual(request.session["group_id"], "group-key")

    def _assert_denied_and_cleared(self, *, membership_row=None, lookup_error=None):
        request = self._request()

        response, downstream, _, _ = self._call(
            request,
            membership_row=membership_row,
            lookup_error=lookup_error,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("control:dashboard"))
        downstream.assert_not_called()
        for key in self.TENANT_STATE:
            self.assertNotIn(key, request.session)

    def test_inactive_membership_is_denied(self):
        self._assert_denied_and_cleared()

    def test_inactive_group_is_denied(self):
        self._assert_denied_and_cleared()

    def test_missing_group_db_config_is_denied(self):
        self._assert_denied_and_cleared()

    def test_alias_mismatch_is_denied(self):
        self._assert_denied_and_cleared()

    def test_missing_membership_is_denied(self):
        self._assert_denied_and_cleared()

    def test_registered_alias_does_not_bypass_membership_lookup(self):
        request = self._request()

        response, downstream, cursor, mocked_connections = self._call(
            request,
            membership_row=None,
        )

        self.assertEqual(response.status_code, 302)
        downstream.assert_not_called()
        cursor.execute.assert_called_once()
        mocked_connections.__getitem__.assert_called_once_with("default")

    def test_lookup_exception_fails_closed(self):
        self._assert_denied_and_cleared(
            lookup_error=RuntimeError("sanitized test failure")
        )

    def test_api_request_receives_sanitized_forbidden_response(self):
        request = self._request(
            "/api/tenant-resource/",
            HTTP_ACCEPT="application/json",
        )

        response, downstream, _, _ = self._call(request, membership_row=None)

        self.assertEqual(response.status_code, 403)
        self.assertJSONEqual(response.content, {"detail": "Tenant access denied."})
        downstream.assert_not_called()
        for key in self.TENANT_STATE:
            self.assertNotIn(key, request.session)

    @override_settings(CENTRAL_DB_ALIAS="default")
    def test_central_route_passes_without_membership_lookup(self):
        request = self._request(
            "/control/",
            session={"tenant_db_alias": "default"},
        )

        response, downstream, _, mocked_connections = self._call(request)

        self.assertEqual(response.status_code, 200)
        downstream.assert_called_once_with(request)
        mocked_connections.__getitem__.assert_not_called()

    def test_public_and_break_glass_paths_pass_without_membership_lookup(self):
        paths = (
            "/login/",
            "/signup/",
            "/control/logout/",
            "/control/set-password/token/",
            "/control/account/set-password/token/",
            "/static/app.css",
            "/media/file/",
            "/health/",
            "/check/",
            "/admin/",
        )

        for path in paths:
            with self.subTest(path=path):
                request = self._request(path)
                response, downstream, _, mocked_connections = self._call(request)

                self.assertEqual(response.status_code, 200)
                downstream.assert_called_once_with(request)
                mocked_connections.__getitem__.assert_not_called()

    def test_middleware_order_is_after_account_guard_and_before_tenant_authz(self):
        middleware = list(settings.MIDDLEWARE)
        guard_index = middleware.index(
            "control.middleware.TenantMembershipFreshnessGuardMiddleware"
        )

        self.assertGreater(
            guard_index,
            middleware.index(
                "control.middleware.CentralAccountActiveGuardMiddleware"
            ),
        )
        self.assertLess(
            guard_index,
            middleware.index("control.middleware.TenantMiddleware"),
        )
        self.assertLess(
            guard_index,
            middleware.index("control.middleware.CentralGuardMiddleware"),
        )
        self.assertLess(
            guard_index,
            middleware.index("control.gf_authz.middleware.GFAuthzContextMiddleware"),
        )
