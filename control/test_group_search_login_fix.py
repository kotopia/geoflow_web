from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, SimpleTestCase
from django.urls import resolve, reverse

from control.views_auth import login_view
from control.views_groups import group_select_view


class GroupSearchLoginFixTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _request_with_session(self, method="get", data=None):
        request = getattr(self.factory, method)("/", data=data or {})
        SessionMiddleware(lambda req: None).process_request(request)
        request.session.save = MagicMock()
        request.user = SimpleNamespace(is_authenticated=False, email="")
        request._dont_enforce_csrf_checks = True
        return request

    def _login_request(self, tenants):
        request = self._request_with_session(
            "post",
            {"email": "account", "password": "password"},
        )
        cursor = MagicMock()
        cursor.fetchone.return_value = ("user-key", "password-hash")
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        user = SimpleNamespace(backend=None)
        user_model = MagicMock()
        user_model.objects.get_or_create.return_value = (user, False)

        mocked_connections = MagicMock()
        mocked_connections.__getitem__.return_value = connection
        patches = (
            patch("control.views_auth.connections", mocked_connections),
            patch("control.views_auth.check_password", return_value=True),
            patch("control.views_auth.identify_hasher", side_effect=ValueError),
            patch("control.views_auth.get_user_model", return_value=user_model),
            patch("control.views_auth.login"),
            patch("control.views_auth.rotate_token"),
            patch("control.views_auth.logger.info"),
            patch("control.views_auth.C.list_tenants_for_user", return_value=tenants),
            patch("control.views_auth.C.list_roles_for_user_in_group", return_value=[]),
        )
        return request, patches

    def _call_login(self, tenants):
        request, patches = self._login_request(tenants)
        entered = []
        try:
            for patcher in patches:
                entered.append(patcher.start())
            response = login_view(request)
        finally:
            for patcher in reversed(patches):
                patcher.stop()
        return request, response

    def test_multi_tenant_login_redirects_to_namespaced_group_search(self):
        candidates = [
            {"id": "group-a", "db_alias": "tenant-a"},
            {"id": "group-b", "db_alias": "tenant-b"},
        ]

        _, response = self._call_login(candidates)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("control:group_search"))
        self.assertNotEqual(response.url, "group_search")

    def test_control_group_search_route_resolves(self):
        match = resolve(reverse("control:group_search"))

        self.assertEqual(match.url_name, "group_search")
        self.assertEqual(match.namespace, "control")

    @patch("control.views_groups.ensure_user_from_request", return_value="user-key")
    def test_group_select_rejects_candidate_not_in_session(self, _ensure_user):
        request = self._request_with_session()
        request.session["tenant_candidates"] = [
            {"id": "group-a", "db_alias": "tenant-a"}
        ]

        response = group_select_view(request, "group-other")

        self.assertEqual(response.status_code, 403)
        self.assertNotIn("tenant_db_alias", request.session)

    @patch("control.views_groups.C.list_roles_for_user_in_group")
    @patch("control.views_groups.ensure_user_from_request", return_value="user-key")
    def test_valid_group_select_sets_session_and_redirects_after_login(
        self, _ensure_user, list_roles
    ):
        roles = [{"code": "member"}]
        list_roles.return_value = roles
        request = self._request_with_session()
        request.session["tenant_candidates"] = [
            {"id": "group-a", "db_alias": "tenant-a"}
        ]

        response = group_select_view(request, "group-a")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("after_login"))
        self.assertNotEqual(response.url, "post_login_redirect")
        self.assertEqual(request.session["group_uuid"], "group-a")
        self.assertEqual(request.session["group_id"], "group-a")
        self.assertEqual(request.session["tenant_db_alias"], "tenant-a")
        self.assertEqual(request.session["db_key"], "tenant-a")
        self.assertEqual(request.session["roles"], roles)
        self.assertNotIn("tenant_candidates", request.session)
        list_roles.assert_called_once_with("user-key", "group-a")

    @patch("control.views_groups.connections")
    @patch("control.views_groups.C.list_roles_for_user_in_group", return_value=[])
    @patch("control.views_groups.ensure_user_from_request", return_value="user-key")
    def test_group_select_does_not_access_tenant_database(
        self, _ensure_user, _list_roles, connections
    ):
        request = self._request_with_session()
        request.session["tenant_candidates"] = [
            {"id": "group-a", "db_alias": "tenant-a"}
        ]

        response = group_select_view(request, "group-a")

        self.assertEqual(response.status_code, 302)
        connections.assert_not_called()

    def test_single_tenant_login_behavior_is_unchanged(self):
        tenant = {"id": "group-a", "db_alias": "tenant-a"}

        request, response = self._call_login([tenant])

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("after_login"))
        self.assertEqual(request.session["group_uuid"], tenant["id"])
        self.assertEqual(request.session["group_id"], tenant["id"])
        self.assertEqual(request.session["tenant_db_alias"], tenant["db_alias"])
        self.assertEqual(request.session["db_key"], tenant["db_alias"])
