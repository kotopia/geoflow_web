from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, SimpleTestCase
from django.urls import resolve, reverse

from control.views_auth import (
    _candidate_is_selectable,
    _selectable_tenant_candidates,
    login_view,
)
from control.views_groups import group_search_view, group_select_view


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

    def _login_request(self, tenants, selectable=None):
        if selectable is None:
            selectable = tenants
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
            patch("control.views_auth.C.list_tenants_for_user", return_value=tenants),
            patch(
                "control.views_auth._selectable_tenant_candidates",
                return_value=selectable,
            ),
            patch("control.views_auth.C.list_roles_for_user_in_group", return_value=[]),
        )
        return request, patches

    def _call_login(self, tenants, selectable=None):
        request, patches = self._login_request(tenants, selectable)
        entered = []
        try:
            for patcher in patches:
                entered.append(patcher.start())
            response = login_view(request)
        finally:
            for patcher in reversed(patches):
                patcher.stop()
        return request, response

    def _candidate(self, **overrides):
        candidate = {
            "id": "group-a",
            "code": "workspace",
            "name": "Workspace",
            "db_alias": "tenant-a",
        }
        candidate.update(overrides)
        return candidate

    def _membership(
        self,
        *,
        membership_status="active",
        group_status="active",
        include_config=True,
        **config_overrides,
    ):
        config_values = {
            "db_alias": "tenant-a",
            "db_name": "database",
            "db_host": "host",
            "db_port": 5432,
            "db_user": "user",
            "db_password": "password",
        }
        config_values.update(config_overrides)
        group_values = {
            "status": group_status,
        }
        if include_config:
            group_values["groupdbconfig"] = SimpleNamespace(**config_values)
        return SimpleNamespace(
            group_id="group-a",
            status=membership_status,
            group=SimpleNamespace(**group_values),
        )

    def test_complete_active_candidate_is_selectable(self):
        self.assertTrue(
            _candidate_is_selectable(
                self._candidate(),
                self._membership(),
            )
        )

    def test_incomplete_or_inactive_candidates_are_excluded(self):
        cases = (
            ("inactive-membership", self._candidate(), self._membership(membership_status="inactive")),
            ("inactive-group", self._candidate(), self._membership(group_status="inactive")),
            ("missing-config", self._candidate(), self._membership(include_config=False)),
            ("missing-alias", self._candidate(db_alias=""), self._membership()),
            ("alias-mismatch", self._candidate(db_alias="tenant-b"), self._membership()),
            ("missing-db-name", self._candidate(), self._membership(db_name="")),
            ("missing-host", self._candidate(), self._membership(db_host="")),
            ("missing-port", self._candidate(), self._membership(db_port=None)),
            ("missing-user", self._candidate(), self._membership(db_user="")),
            ("missing-password", self._candidate(), self._membership(db_password="")),
            ("missing-code", self._candidate(code=""), self._membership()),
            ("missing-name", self._candidate(name=""), self._membership()),
        )

        for label, candidate, membership in cases:
            with self.subTest(label=label):
                self.assertFalse(
                    _candidate_is_selectable(candidate, membership)
                )

    @patch("control.views_auth.UserGroupMap.objects.using")
    def test_candidate_filter_returns_only_selectable_memberships(self, using):
        valid = self._candidate()
        invalid = self._candidate(
            id="group-b",
            code="other",
            name="Other",
            db_alias="tenant-b",
        )
        invalid_membership = self._membership(
            membership_status="inactive"
        )
        invalid_membership.group_id = "group-b"
        invalid_membership.group.groupdbconfig.db_alias = "tenant-b"
        queryset = MagicMock()
        queryset.filter.return_value = [
            self._membership(),
            invalid_membership,
        ]
        using.return_value.select_related.return_value = queryset

        result = _selectable_tenant_candidates(
            "user-key",
            [valid, invalid],
        )

        self.assertEqual(result, [valid])

    def test_login_session_contains_only_selectable_candidates(self):
        valid_a = self._candidate()
        valid_b = self._candidate(
            id="group-b",
            code="other",
            name="Other",
            db_alias="tenant-b",
        )
        invalid = self._candidate(
            id="group-c",
            code="blocked",
            name="Blocked",
            db_alias="tenant-c",
        )

        request, response = self._call_login(
            [valid_a, valid_b, invalid],
            [valid_a, valid_b],
        )

        self.assertEqual(response.url, reverse("control:group_search"))
        self.assertEqual(
            request.session["tenant_candidates"],
            [valid_a, valid_b],
        )

    def test_one_selectable_candidate_keeps_single_tenant_flow(self):
        valid = self._candidate()
        invalid = self._candidate(
            id="group-b",
            code="blocked",
            name="Blocked",
            db_alias="tenant-b",
        )

        request, response = self._call_login(
            [valid, invalid],
            [valid],
        )

        self.assertEqual(response.url, reverse("after_login"))
        self.assertEqual(request.session["group_id"], valid["id"])
        self.assertNotIn("tenant_candidates", request.session)

    def test_zero_selectable_candidates_routes_to_central_flow(self):
        invalid = self._candidate()

        request, response = self._call_login([invalid], [])

        self.assertEqual(response.url, reverse("after_login"))
        self.assertEqual(request.session["tenant_db_alias"], "default")
        self.assertNotIn("tenant_candidates", request.session)

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

    @patch("control.views_groups.render")
    def test_group_search_renders_only_session_candidates(self, render):
        request = self._request_with_session()
        request.session["tenant_candidates"] = [
            {
                "id": "group-a",
                "code": "allowed",
                "name": "Allowed",
                "db_alias": "tenant-a",
            }
        ]

        group_search_view(request)

        rows = render.call_args.args[2]["rows"]
        self.assertEqual(rows, [("group-a", "allowed", "Allowed", "active")])
        self.assertNotIn("group-other", [row[0] for row in rows])

    @patch("django.db.connections")
    @patch("control.views_groups.render")
    def test_group_search_does_not_query_broad_group_list(
        self, render, connections
    ):
        request = self._request_with_session()
        request.session["tenant_candidates"] = [
            {
                "id": "group-a",
                "code": "allowed",
                "name": "Allowed",
                "db_alias": "tenant-a",
            }
        ]

        group_search_view(request)

        render.assert_called_once()
        connections.assert_not_called()

    def test_group_search_without_candidates_redirects_to_login(self):
        request = self._request_with_session()

        response = group_search_view(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("login"))

    @patch("control.views_groups.C.list_roles_for_user_in_group", return_value=[])
    @patch("control.views_groups.ensure_user_from_request", return_value="user-key")
    @patch("control.views_groups.render")
    def test_rendered_candidate_can_be_selected(
        self, render, _ensure_user, _list_roles
    ):
        request = self._request_with_session()
        request.session["tenant_candidates"] = [
            {
                "id": "group-a",
                "code": "allowed",
                "name": "Allowed",
                "db_alias": "tenant-a",
            }
        ]
        group_search_view(request)
        rendered_id = render.call_args.args[2]["rows"][0][0]

        response = group_select_view(request, rendered_id)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("after_login"))

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

    @patch("control.views_groups.C.list_roles_for_user_in_group", return_value=[])
    @patch("control.views_groups.ensure_user_from_request", return_value="user-key")
    def test_group_select_does_not_access_tenant_database(
        self, _ensure_user, _list_roles
    ):
        request = self._request_with_session()
        request.session["tenant_candidates"] = [
            {"id": "group-a", "db_alias": "tenant-a"}
        ]

        response = group_select_view(request, "group-a")

        self.assertEqual(response.status_code, 302)

    def test_single_tenant_login_behavior_is_unchanged(self):
        tenant = {"id": "group-a", "db_alias": "tenant-a"}

        request, response = self._call_login([tenant])

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("after_login"))
        self.assertEqual(request.session["group_uuid"], tenant["id"])
        self.assertEqual(request.session["group_id"], tenant["id"])
        self.assertEqual(request.session["tenant_db_alias"], tenant["db_alias"])
        self.assertEqual(request.session["db_key"], tenant["db_alias"])
