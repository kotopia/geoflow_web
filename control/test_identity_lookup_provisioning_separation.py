from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase, override_settings

from control.decorators import require_central_admin
from control.gf_authz.services import gf_load_user_context
from control.services_identity import (
    ensure_user_from_request,
    lookup_user_id_from_request,
)
from control.views_groups import group_select_view


class IdentityLookupProvisioningSeparationTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _request(self):
        request = self.factory.get("/control/groups/select/group-key/")
        request.session = {
            "tenant_candidates": [
                {"id": "group-key", "db_alias": "tenant-key"}
            ]
        }
        request.user = SimpleNamespace(
            is_authenticated=True,
            email="account@example.invalid",
            username="account@example.invalid",
        )
        return request

    def _connections(self, row):
        cursor = MagicMock()
        cursor.fetchone.return_value = row
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        mocked_connections = MagicMock()
        mocked_connections.__getitem__.return_value = connection
        return mocked_connections, cursor

    @override_settings(CENTRAL_DB_ALIAS="central")
    def test_lookup_returns_existing_central_user_without_provisioning(self):
        request = self._request()
        mocked_connections, cursor = self._connections(("user-key",))

        with (
            patch("control.services_identity.connections", mocked_connections),
            patch("control.services_identity.ensure_user_from_request") as ensure,
            patch("control.services_identity.get_or_create_user_by_email") as create,
        ):
            result = lookup_user_id_from_request(request)

        self.assertEqual(result, "user-key")
        mocked_connections.__getitem__.assert_called_once_with("central")
        cursor.execute.assert_called_once()
        ensure.assert_not_called()
        create.assert_not_called()

    @override_settings(CENTRAL_DB_ALIAS="central")
    def test_lookup_returns_none_for_missing_user_without_provisioning(self):
        request = self._request()
        mocked_connections, cursor = self._connections(None)

        with (
            patch("control.services_identity.connections", mocked_connections),
            patch("control.services_identity.ensure_user_from_request") as ensure,
            patch("control.services_identity.get_or_create_user_by_email") as create,
        ):
            result = lookup_user_id_from_request(request)

        self.assertIsNone(result)
        cursor.execute.assert_called_once()
        ensure.assert_not_called()
        create.assert_not_called()

    @patch("control.views_groups.messages.error")
    @patch("control.views_groups.lookup_user_id_from_request", return_value=None)
    def test_group_selection_missing_user_fails_closed_without_provisioning(
        self,
        lookup_user,
        _message,
    ):
        request = self._request()

        with patch("control.services_identity.ensure_user_from_request") as ensure:
            response = group_select_view(request, "group-key")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/login/")
        self.assertNotIn("tenant_db_alias", request.session)
        lookup_user.assert_called_once_with(request)
        ensure.assert_not_called()

    @patch("control.decorators.lookup_user_id_from_request", return_value=None)
    def test_admin_authorization_missing_user_fails_closed(self, lookup_user):
        downstream = MagicMock(return_value="allowed")
        request = self._request()

        response = require_central_admin(downstream)(request)

        self.assertEqual(response.status_code, 403)
        downstream.assert_not_called()
        lookup_user.assert_called_once_with(request)

    @override_settings(
        GF_AUTHZ_CENTRAL_ALIAS="default",
        GF_AUTHZ_TABLES={},
    )
    def test_authorization_context_missing_user_does_not_provision(self):
        request = self._request()
        mocked_connections, _ = self._connections(None)

        with (
            patch("control.gf_authz.services.connections", mocked_connections),
            patch(
                "control.gf_authz.services._resolve_central_user_uuid",
                return_value=None,
            ),
            patch("control.services_identity.ensure_user_from_request") as ensure,
            patch("control.services_identity.get_or_create_user_by_email") as create,
        ):
            context = gf_load_user_context(request)

        self.assertEqual(context["roles"], [])
        self.assertEqual(context["perms"], [])
        ensure.assert_not_called()
        create.assert_not_called()

    def test_legacy_ensure_helper_is_disabled(self):
        with self.assertRaisesRegex(RuntimeError, "implicit central account provisioning is disabled"):
            ensure_user_from_request(self._request())
        self.assertIn("Disabled legacy helper", ensure_user_from_request.__doc__)
