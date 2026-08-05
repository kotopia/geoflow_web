from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase
from django.urls import resolve, reverse

from control import views_users_admin


class CentralDashboardAuthenticationGuardTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_anonymous_dashboard_request_redirects_to_login(self):
        request = self.factory.get(reverse("control:dashboard"))
        request.user = AnonymousUser()

        response = views_users_admin.dashboard(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            f'{reverse("login")}?next={reverse("control:dashboard")}',
        )

    def test_authenticated_dashboard_request_keeps_existing_render(self):
        request = self.factory.get(reverse("control:dashboard"))
        request.user = SimpleNamespace(is_authenticated=True)

        with patch.object(
            views_users_admin,
            "render",
            return_value=HttpResponse("ok"),
        ) as render:
            response = views_users_admin.dashboard(request)

        self.assertEqual(response.status_code, 200)
        render.assert_called_once_with(
            request,
            "control/dashboard.html",
            {},
        )

    def test_dashboard_url_reverse_and_resolve_are_unchanged(self):
        dashboard_url = reverse("control:dashboard")

        self.assertEqual(dashboard_url, "/control/")
        self.assertIs(resolve(dashboard_url).func, views_users_admin.dashboard)

    def test_existing_central_admin_urls_remain_available(self):
        user_id = UUID(int=1)

        self.assertEqual(
            reverse("control:users_list_admin"),
            "/control/mgmt/users/",
        )
        self.assertEqual(
            reverse("control:users_detail_admin", args=[user_id]),
            f"/control/mgmt/users/{user_id}/",
        )
        self.assertEqual(
            reverse("control:group_list_admin"),
            "/control/central/groups/",
        )
        self.assertEqual(
            reverse("control:join_requests_pending"),
            "/control/mgmt/join-requests/",
        )
