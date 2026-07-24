from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import reverse

from control.views_auth import (
    ensure_tenant_connection_for_session,
    post_login_redirect,
)


class TenantConnectionRegistrationTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _request(self, session=None, post_data=None):
        request = self.factory.get("/", data=post_data or {})
        request.session = session or {}
        return request

    def _config(self, **overrides):
        values = {
            "db_alias": "tenant-key",
            "db_name": "database-name",
            "db_host": "database-host",
            "db_port": 5432,
            "db_user": "database-user",
            "db_password": "database-password",
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def _connections(self, databases):
        mocked_connections = MagicMock()
        mocked_connections.databases = databases
        return mocked_connections

    def _mock_authorized_config(self, config=None, authorized=True):
        membership_filter = MagicMock()
        membership_filter.exists.return_value = authorized
        membership_using = MagicMock()
        membership_using.filter.return_value = membership_filter

        config_filter = MagicMock()
        config_filter.first.return_value = config
        config_related = MagicMock()
        config_related.filter.return_value = config_filter
        config_using = MagicMock()
        config_using.select_related.return_value = config_related

        return (
            patch(
                "control.views_auth.UserGroupMap.objects.using",
                return_value=membership_using,
            ),
            patch(
                "control.views_auth.GroupDBConfig.objects.using",
                return_value=config_using,
            ),
        )

    @override_settings(CENTRAL_DB_ALIAS="default")
    def test_central_flow_succeeds_without_registry_mutation(self):
        databases = {"default": {"ENGINE": "central-engine"}}
        request = self._request({"tenant_db_alias": "default"})

        with patch(
            "control.views_auth.connections", self._connections(databases)
        ):
            result = ensure_tenant_connection_for_session(request)

        self.assertTrue(result)
        self.assertEqual(databases, {"default": {"ENGINE": "central-engine"}})

    @override_settings(CENTRAL_DB_ALIAS="default")
    def test_registered_tenant_alias_is_reused_without_mutation(self):
        databases = {
            "default": {"ENGINE": "central-engine"},
            "tenant-key": {"ENGINE": "existing-engine"},
        }
        original = dict(databases["tenant-key"])
        request = self._request(
            {"tenant_db_alias": "tenant-key", "group_id": "group-key"}
        )

        with patch(
            "control.views_auth.connections", self._connections(databases)
        ):
            result = ensure_tenant_connection_for_session(request)

        self.assertTrue(result)
        self.assertEqual(databases["tenant-key"], original)

    @override_settings(CENTRAL_DB_ALIAS="default", DATABASES={"default": {}})
    @patch("control.views_auth.ensure_user_from_request", return_value="user-key")
    def test_valid_central_config_registers_missing_alias(self, _ensure_user):
        databases = {
            "default": {
                "ENGINE": "central-engine",
                "OPTIONS": {"sslmode": "require"},
            }
        }
        request = self._request(
            {"tenant_db_alias": "tenant-key", "group_id": "group-key"}
        )
        membership_patch, config_patch = self._mock_authorized_config(
            self._config()
        )

        with (
            patch(
                "control.views_auth.connections", self._connections(databases)
            ),
            membership_patch,
            config_patch,
        ):
            result = ensure_tenant_connection_for_session(request)

        self.assertTrue(result)
        self.assertIn("tenant-key", databases)
        self.assertEqual(
            databases["tenant-key"]["ENGINE"],
            "django.contrib.gis.db.backends.postgis",
        )

    @override_settings(CENTRAL_DB_ALIAS="default", DATABASES={"default": {}})
    @patch("control.views_auth.ensure_user_from_request", return_value="user-key")
    def test_missing_config_fails_safely(self, _ensure_user):
        databases = {"default": {"ENGINE": "central-engine"}}
        request = self._request(
            {"tenant_db_alias": "tenant-key", "group_id": "group-key"}
        )
        membership_patch, config_patch = self._mock_authorized_config(None)

        with (
            patch(
                "control.views_auth.connections", self._connections(databases)
            ),
            membership_patch,
            config_patch,
        ):
            result = ensure_tenant_connection_for_session(request)

        self.assertFalse(result)
        self.assertNotIn("tenant-key", databases)

    @override_settings(CENTRAL_DB_ALIAS="default", DATABASES={"default": {}})
    @patch("control.views_auth.ensure_user_from_request", return_value="user-key")
    def test_incomplete_config_fails_safely(self, _ensure_user):
        databases = {"default": {"ENGINE": "central-engine"}}
        request = self._request(
            {"tenant_db_alias": "tenant-key", "group_id": "group-key"}
        )
        membership_patch, config_patch = self._mock_authorized_config(
            self._config(db_host="")
        )

        with (
            patch(
                "control.views_auth.connections", self._connections(databases)
            ),
            membership_patch,
            config_patch,
        ):
            result = ensure_tenant_connection_for_session(request)

        self.assertFalse(result)
        self.assertNotIn("tenant-key", databases)

    @override_settings(CENTRAL_DB_ALIAS="default", DATABASES={"default": {}})
    @patch("control.views_auth.ensure_user_from_request", return_value="user-key")
    def test_inactive_membership_fails_safely(self, _ensure_user):
        databases = {"default": {"ENGINE": "central-engine"}}
        request = self._request(
            {"tenant_db_alias": "tenant-key", "group_id": "group-key"}
        )
        membership_patch, config_patch = self._mock_authorized_config(
            self._config(), authorized=False
        )

        with (
            patch(
                "control.views_auth.connections", self._connections(databases)
            ),
            membership_patch,
            config_patch,
        ):
            result = ensure_tenant_connection_for_session(request)

        self.assertFalse(result)
        self.assertNotIn("tenant-key", databases)

    @override_settings(CENTRAL_DB_ALIAS="default", DATABASES={"default": {}})
    @patch("control.views_auth.ensure_user_from_request", return_value="user-key")
    def test_inactive_group_config_fails_safely(self, _ensure_user):
        databases = {"default": {"ENGINE": "central-engine"}}
        request = self._request(
            {"tenant_db_alias": "tenant-key", "group_id": "group-key"}
        )
        membership_filter = MagicMock()
        membership_filter.exists.return_value = True
        membership_using = MagicMock()
        membership_using.filter.return_value = membership_filter
        config_filter = MagicMock()
        config_filter.first.return_value = None
        config_related = MagicMock()
        config_related.filter.return_value = config_filter
        config_using = MagicMock()
        config_using.select_related.return_value = config_related

        with (
            patch(
                "control.views_auth.connections", self._connections(databases)
            ),
            patch(
                "control.views_auth.UserGroupMap.objects.using",
                return_value=membership_using,
            ),
            patch(
                "control.views_auth.GroupDBConfig.objects.using",
                return_value=config_using,
            ),
        ):
            result = ensure_tenant_connection_for_session(request)

        self.assertFalse(result)
        self.assertNotIn("tenant-key", databases)
        config_related.filter.assert_called_once_with(
            group_id="group-key", group__status="active"
        )

    @override_settings(CENTRAL_DB_ALIAS="default", DATABASES={"default": {}})
    @patch("control.views_auth.ensure_user_from_request", return_value="user-key")
    def test_alias_mismatch_fails_safely(self, _ensure_user):
        databases = {"default": {"ENGINE": "central-engine"}}
        request = self._request(
            {"tenant_db_alias": "tenant-key", "group_id": "group-key"}
        )
        membership_patch, config_patch = self._mock_authorized_config(
            self._config(db_alias="different-key")
        )

        with (
            patch(
                "control.views_auth.connections", self._connections(databases)
            ),
            membership_patch,
            config_patch,
        ):
            result = ensure_tenant_connection_for_session(request)

        self.assertFalse(result)
        self.assertNotIn("tenant-key", databases)

    @override_settings(CENTRAL_DB_ALIAS="default")
    def test_helper_ignores_request_payload_alias(self):
        databases = {"default": {"ENGINE": "central-engine"}}
        request = self._request(
            {"tenant_db_alias": "default"},
            post_data={"tenant_db_alias": "untrusted-key"},
        )

        with patch(
            "control.views_auth.connections", self._connections(databases)
        ):
            result = ensure_tenant_connection_for_session(request)

        self.assertTrue(result)
        self.assertNotIn("untrusted-key", databases)

    @override_settings(CENTRAL_DB_ALIAS="default")
    @patch("control.views_auth.redirect")
    @patch(
        "control.views_auth.ensure_tenant_connection_for_session",
        return_value=True,
    )
    def test_post_login_prepares_connection_before_tenant_redirect(
        self, ensure_connection, redirect
    ):
        calls = []
        ensure_connection.side_effect = lambda request: calls.append("prepare") or True
        redirect.side_effect = lambda target: calls.append(("redirect", target)) or target
        request = self._request(
            {"tenant_db_alias": "tenant-key", "group_id": "group-key"}
        )

        response = post_login_redirect(request)

        self.assertEqual(response, "/")
        self.assertEqual(calls, ["prepare", ("redirect", "/")])

    @override_settings(CENTRAL_DB_ALIAS="default")
    @patch(
        "control.views_auth.ensure_tenant_connection_for_session",
        return_value=False,
    )
    def test_post_login_fails_safely_when_preparation_fails(
        self, ensure_connection
    ):
        request = self._request(
            {
                "tenant_db_alias": "tenant-key",
                "db_key": "tenant-key",
                "group_id": "group-key",
                "group_uuid": "group-key",
                "roles": [],
            }
        )

        response = post_login_redirect(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("control:dashboard"))
        self.assertEqual(request.session["tenant_db_alias"], "default")
        self.assertNotIn("group_id", request.session)
        ensure_connection.assert_called_once_with(request)

    @override_settings(CENTRAL_DB_ALIAS="default")
    @patch(
        "control.views_auth.ensure_tenant_connection_for_session",
        return_value=True,
    )
    def test_single_tenant_known_alias_flow_remains_valid(
        self, ensure_connection
    ):
        request = self._request(
            {"tenant_db_alias": "tenant-key", "group_id": "group-key"}
        )

        response = post_login_redirect(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/")
        ensure_connection.assert_called_once_with(request)
