from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse

from control.middleware import CentralAccountActiveGuardMiddleware


class CentralAccountActiveGuardMiddlewareTests(SimpleTestCase):
    SESSION_STATE = {
        "tenant_db_alias": "tenant-alias",
        "db_key": "tenant-alias",
        "group_id": "group-key",
        "group_uuid": "group-key",
        "tenant_candidates": [{"id": "candidate-key"}],
        "roles": [{"code": "role"}],
        "gf_authz_ctx": {"perms": ["permission"]},
        "gf_perms": ["permission"],
        "gf_roles": ["role"],
    }

    def setUp(self):
        self.factory = RequestFactory()

    def _request(self, path="/protected/", *, authenticated=True, **headers):
        request = self.factory.get(path, **headers)
        SessionMiddleware(lambda req: None).process_request(request)
        request.session.update(self.SESSION_STATE)
        request.user = SimpleNamespace(
            is_authenticated=authenticated,
            email="account",
            username="account",
        )
        return request

    def _middleware_call(self, request, account_row=(True,), lookup_error=None):
        downstream = MagicMock(return_value=MagicMock(status_code=200))
        middleware = CentralAccountActiveGuardMiddleware(downstream)
        cursor = MagicMock()
        cursor.fetchone.return_value = account_row
        if lookup_error is not None:
            cursor.execute.side_effect = lookup_error
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        mocked_connections = MagicMock()
        mocked_connections.__getitem__.return_value = connection

        with patch("control.middleware.connections", mocked_connections):
            response = middleware(request)

        return response, downstream, mocked_connections

    def test_anonymous_request_passes_without_central_lookup(self):
        request = self._request(authenticated=False)

        response, downstream, mocked_connections = self._middleware_call(request)

        self.assertEqual(response.status_code, 200)
        downstream.assert_called_once_with(request)
        mocked_connections.__getitem__.assert_not_called()

    def test_public_paths_pass_without_central_lookup(self):
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
                response, downstream, mocked_connections = self._middleware_call(
                    request
                )

                self.assertEqual(response.status_code, 200)
                downstream.assert_called_once_with(request)
                mocked_connections.__getitem__.assert_not_called()

    def test_active_central_user_reaches_downstream(self):
        request = self._request()

        response, downstream, _ = self._middleware_call(request, (True,))

        self.assertEqual(response.status_code, 200)
        downstream.assert_called_once_with(request)
        self.assertEqual(request.session["group_id"], "group-key")

    def test_inactive_central_user_is_logged_out_and_redirected(self):
        for active_state in (False, None):
            with self.subTest(active_state=active_state):
                request = self._request()

                response, downstream, _ = self._middleware_call(
                    request,
                    (active_state,),
                )

                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.url, reverse("login"))
                downstream.assert_not_called()
                self.assertFalse(request.user.is_authenticated)
                for key in self.SESSION_STATE:
                    self.assertNotIn(key, request.session)

    def test_missing_central_user_is_logged_out_and_redirected(self):
        request = self._request()

        response, downstream, _ = self._middleware_call(request, None)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("login"))
        downstream.assert_not_called()
        self.assertFalse(request.user.is_authenticated)
        for key in self.SESSION_STATE:
            self.assertNotIn(key, request.session)

    def test_api_request_receives_sanitized_unauthorized_response(self):
        request = self._request("/api/protected/")

        response, downstream, _ = self._middleware_call(request, (False,))

        self.assertEqual(response.status_code, 401)
        self.assertJSONEqual(
            response.content,
            {"detail": "Authentication required."},
        )
        downstream.assert_not_called()
        for key in self.SESSION_STATE:
            self.assertNotIn(key, request.session)

    def test_ajax_request_receives_sanitized_unauthorized_response(self):
        request = self._request(
            "/protected/",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        response, downstream, _ = self._middleware_call(request, None)

        self.assertEqual(response.status_code, 401)
        downstream.assert_not_called()

    def test_lookup_exception_fails_closed_without_downstream_call(self):
        request = self._request()

        response, downstream, _ = self._middleware_call(
            request,
            lookup_error=RuntimeError("sanitized test failure"),
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("login"))
        downstream.assert_not_called()
        self.assertFalse(request.user.is_authenticated)
        for key in self.SESSION_STATE:
            self.assertNotIn(key, request.session)

    def test_middleware_order_is_after_authentication_and_before_tenant_authz(self):
        middleware = list(settings.MIDDLEWARE)
        guard_index = middleware.index(
            "control.middleware.CentralAccountActiveGuardMiddleware"
        )

        self.assertGreater(
            guard_index,
            middleware.index(
                "django.contrib.auth.middleware.AuthenticationMiddleware"
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
