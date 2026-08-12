from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from control.gf_authz.middleware import GFAuthzContextMiddleware
from control.gf_authz.permissions import gf_has_perm, gf_has_role


class PermissionCacheInvalidationTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _request(self, *, authenticated=True):
        request = self.factory.get("/contracts/")
        request.session = {
            "group_id": "group-key",
            "gf_authz_ctx": {
                "tenant_id": "group-key",
                "roles": ["stale-role"],
                "perms": ["stale.permission"],
                "project_ids": [],
            },
            "gf_roles": ["stale-role"],
            "gf_perms": ["stale.permission"],
        }
        request.user = SimpleNamespace(
            is_authenticated=authenticated,
            email="account@example.invalid",
        )
        return request

    def test_empty_request_caches_do_not_fall_back_to_stale_session_authz(self):
        request = self._request()
        request._gf_roles_cache = set()
        request._gf_perms_cache = set()

        self.assertFalse(gf_has_role(request, "stale-role"))
        self.assertFalse(gf_has_perm(request, "stale.permission"))

    @patch("control.gf_authz.middleware.gf_load_user_context")
    def test_stale_session_context_is_replaced_from_authoritative_source(
        self,
        load_context,
    ):
        fresh_context = {
            "tenant_id": "group-key",
            "roles": ["fresh-role"],
            "perms": ["fresh.permission"],
            "project_ids": ["project-key"],
        }
        load_context.return_value = fresh_context
        request = self._request()

        result = GFAuthzContextMiddleware(lambda req: None).process_request(request)

        self.assertIsNone(result)
        load_context.assert_called_once_with(request)
        self.assertEqual(request.session["gf_authz_ctx"], fresh_context)
        self.assertEqual(request.session["gf_roles"], ["fresh-role"])
        self.assertEqual(request.session["gf_perms"], ["fresh.permission"])
        self.assertFalse(gf_has_role(request, "stale-role"))
        self.assertFalse(gf_has_perm(request, "stale.permission"))
        self.assertTrue(gf_has_role(request, "fresh-role"))
        self.assertTrue(gf_has_perm(request, "fresh.permission"))

    @patch("control.gf_authz.middleware.logger")
    @patch("control.gf_authz.middleware.gf_load_user_context")
    def test_context_refresh_failure_replaces_stale_permissions_with_empty_context(
        self,
        load_context,
        logger,
    ):
        load_context.side_effect = RuntimeError("sanitized test failure")
        request = self._request()

        result = GFAuthzContextMiddleware(lambda req: None).process_request(request)

        self.assertIsNone(result)
        self.assertEqual(request.session["gf_roles"], [])
        self.assertEqual(request.session["gf_perms"], [])
        self.assertEqual(request._gf_roles_cache, set())
        self.assertEqual(request._gf_perms_cache, set())
        self.assertFalse(gf_has_role(request, "stale-role"))
        self.assertFalse(gf_has_perm(request, "stale.permission"))
        logger.warning.assert_called_once_with(
            "Authorization context refresh failed"
        )

    @patch("control.gf_authz.middleware.gf_load_user_context")
    def test_active_request_with_fresh_context_continues_normally(
        self,
        load_context,
    ):
        load_context.return_value = {
            "tenant_id": "group-key",
            "roles": ["member"],
            "perms": ["contracts.view"],
            "project_ids": [],
        }
        request = self._request()

        result = GFAuthzContextMiddleware(lambda req: None).process_request(request)

        self.assertIsNone(result)
        self.assertTrue(gf_has_role(request, "member"))
        self.assertTrue(gf_has_perm(request, "contracts.view"))

    @patch("control.gf_authz.middleware.gf_load_user_context")
    def test_anonymous_request_does_not_load_authorization_context(
        self,
        load_context,
    ):
        request = self._request(authenticated=False)

        result = GFAuthzContextMiddleware(lambda req: None).process_request(request)

        self.assertIsNone(result)
        load_context.assert_not_called()