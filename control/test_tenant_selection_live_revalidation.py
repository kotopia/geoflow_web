from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from control.services.tenant_selection import refresh_server_issued_tenant_candidates
from control.views_groups import _refresh_session_candidates, group_select_view


class TenantSelectionRefreshServiceTests(SimpleTestCase):
    def test_refresh_keeps_only_originally_issued_live_candidates(self):
        issued = [
            {"id": "group-a", "code": "a", "name": "A", "db_alias": "a_db"},
            {"id": "group-b", "code": "b", "name": "B", "db_alias": "b_db"},
        ]
        current = [
            {"id": "group-a", "code": "a", "name": "A", "db_alias": "a_db"},
            {"id": "group-c", "code": "c", "name": "C", "db_alias": "c_db"},
        ]

        with patch(
            "control.services.tenant_selection.C.list_tenants_for_user",
            return_value=current,
        ), patch(
            "control.services.tenant_selection.selectable_tenant_candidates",
            side_effect=lambda user_id, candidates: candidates,
        ) as selectable:
            refreshed = refresh_server_issued_tenant_candidates("user-a", issued)

        self.assertEqual([item["id"] for item in refreshed], ["group-a"])
        selectable.assert_called_once_with("user-a", [current[0]])

    def test_refresh_fails_closed_when_central_lookup_fails(self):
        with patch(
            "control.services.tenant_selection.C.list_tenants_for_user",
            side_effect=RuntimeError("central lookup unavailable"),
        ):
            refreshed = refresh_server_issued_tenant_candidates(
                "user-a",
                [{"id": "group-a"}],
            )

        self.assertEqual(refreshed, [])


class TenantSelectionSessionTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_refresh_session_replaces_stale_candidate_set(self):
        request = self.factory.get("/groups/search/")
        request.session = {
            "tenant_candidates": [
                {"id": "group-a", "db_alias": "a_db"},
                {"id": "group-b", "db_alias": "b_db"},
            ]
        }
        fresh = [{"id": "group-a", "db_alias": "a_db"}]

        with patch(
            "control.views_groups.refresh_server_issued_tenant_candidates",
            return_value=fresh,
        ):
            result = _refresh_session_candidates(request, "user-a")

        self.assertEqual(result, fresh)
        self.assertEqual(request.session["tenant_candidates"], fresh)

    def test_refresh_session_removes_candidates_when_none_remain(self):
        request = self.factory.get("/groups/search/")
        request.session = {"tenant_candidates": [{"id": "group-a"}]}

        with patch(
            "control.views_groups.refresh_server_issued_tenant_candidates",
            return_value=[],
        ):
            result = _refresh_session_candidates(request, "user-a")

        self.assertEqual(result, [])
        self.assertNotIn("tenant_candidates", request.session)

    def test_group_select_rejects_candidate_revoked_after_login(self):
        request = self.factory.post("/groups/select/group-a/")
        request.user = SimpleNamespace(is_authenticated=True)
        request.session = {
            "tenant_candidates": [
                {
                    "id": "group-a",
                    "code": "a",
                    "name": "A",
                    "db_alias": "a_db",
                }
            ]
        }

        undecorated = group_select_view
        while hasattr(undecorated, "__wrapped__"):
            undecorated = undecorated.__wrapped__

        with patch(
            "control.views_groups.lookup_user_id_from_request",
            return_value="user-a",
        ), patch(
            "control.views_groups.refresh_server_issued_tenant_candidates",
            return_value=[],
        ):
            response = undecorated(request, "group-a")

        self.assertEqual(response.status_code, 403)
        self.assertNotIn("group_id", request.session)
        self.assertNotIn("tenant_db_alias", request.session)

    def test_group_select_commits_only_live_revalidated_candidate(self):
        candidate = {
            "id": "group-a",
            "code": "a",
            "name": "A",
            "db_alias": "a_db",
        }
        request = self.factory.post("/groups/select/group-a/")
        request.user = SimpleNamespace(is_authenticated=True)
        request.session = {"tenant_candidates": [candidate]}

        undecorated = group_select_view
        while hasattr(undecorated, "__wrapped__"):
            undecorated = undecorated.__wrapped__

        with patch(
            "control.views_groups.lookup_user_id_from_request",
            return_value="user-a",
        ), patch(
            "control.views_groups.refresh_server_issued_tenant_candidates",
            return_value=[candidate],
        ), patch(
            "control.views_groups.C.list_roles_for_user_in_group",
            return_value=[{"code": "tenant_admin"}],
        ):
            response = undecorated(request, "group-a")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(request.session["group_uuid"], "group-a")
        self.assertEqual(request.session["group_id"], "group-a")
        self.assertEqual(request.session["tenant_db_alias"], "a_db")
        self.assertEqual(request.session["db_key"], "a_db")
        self.assertEqual(request.session["roles"], [{"code": "tenant_admin"}])
        self.assertNotIn("tenant_candidates", request.session)
