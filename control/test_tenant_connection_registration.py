from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db.utils import ConnectionDoesNotExist
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import reverse

from control.db_router import TenantRouter
from control.middleware import (
    EnsureTenantAliasMiddleware,
    TenantMiddleware,
    current_db_alias,
)
from control.tenant_connections import (
    ensure_tenant_connection_for_session,
)
from control.views_auth import (
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

    def _connections(self, databases, resolve_error=None):
        mocked_connections = MagicMock()
        mocked_connections.databases = databases
        mocked_connections.settings = databases
        if resolve_error is not None:
            mocked_connections.__getitem__.side_effect = resolve_error
        else:
            mocked_connections.__getitem__.return_value = MagicMock()
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
                "control.tenant_connections.UserGroupMap.objects.using",
                return_value=membership_using,
            ),
            patch(
                "control.tenant_connections.GroupDBConfig.objects.using",
                return_value=config_using,
            ),
        )

    @override_settings(CENTRAL_DB_ALIAS="default")
    def test_central_flow_succeeds_without_registry_mutation(self):
        databases = {"default": {"ENGINE": "central-engine"}}
        request = self._request({"tenant_db_alias": "default"})

        with patch(
            "control.tenant_connections.connections", self._connections(databases)
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

        connection_handler = self._connections(databases)
        with patch(
            "control.tenant_connections.connections", connection_handler
        ):
            result = ensure_tenant_connection_for_session(request)

        self.assertTrue(result)
        self.assertEqual(databases["tenant-key"], original)
        connection_handler.__getitem__.assert_called_once_with("tenant-key")

    @override_settings(CENTRAL_DB_ALIAS="default", DATABASES={"default": {}})
    @patch("control.tenant_connections.lookup_user_id_from_request", return_value="user-key")
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

        connection_handler = self._connections(databases)
        with (
            patch("control.tenant_connections.connections", connection_handler),
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
        connection_handler.__getitem__.assert_called_once_with("tenant-key")
        connection_handler.__getitem__.return_value.cursor.assert_not_called()

    @override_settings(CENTRAL_DB_ALIAS="default", DATABASES={"default": {}})
    @patch("control.tenant_connections.lookup_user_id_from_request", return_value="user-key")
    def test_new_registration_is_removed_when_handler_lookup_fails(
        self, _ensure_user
    ):
        databases = {"default": {"ENGINE": "central-engine"}}
        request = self._request(
            {"tenant_db_alias": "tenant-key", "group_id": "group-key"}
        )
        membership_patch, config_patch = self._mock_authorized_config(
            self._config()
        )
        connection_handler = self._connections(
            databases,
            ConnectionDoesNotExist("Handler lookup failed."),
        )

        with (
            patch("control.tenant_connections.connections", connection_handler),
            membership_patch,
            config_patch,
        ):
            result = ensure_tenant_connection_for_session(request)

        self.assertFalse(result)
        self.assertNotIn("tenant-key", databases)
        self.assertNotIn("tenant-key", settings.DATABASES)

    @override_settings(CENTRAL_DB_ALIAS="default")
    def test_preexisting_registration_is_not_removed_when_lookup_fails(self):
        databases = {
            "default": {"ENGINE": "central-engine"},
            "tenant-key": {"ENGINE": "existing-engine"},
        }
        original = dict(databases["tenant-key"])
        request = self._request(
            {"tenant_db_alias": "tenant-key", "group_id": "group-key"}
        )
        connection_handler = self._connections(
            databases,
            ConnectionDoesNotExist("Handler lookup failed."),
        )

        with patch(
            "control.tenant_connections.connections", connection_handler
        ):
            result = ensure_tenant_connection_for_session(request)

        self.assertFalse(result)
        self.assertEqual(databases["tenant-key"], original)

    @override_settings(CENTRAL_DB_ALIAS="default", DATABASES={"default": {}})
    @patch("control.tenant_connections.lookup_user_id_from_request", return_value="user-key")
    def test_missing_config_fails_safely(self, _ensure_user):
        databases = {"default": {"ENGINE": "central-engine"}}
        request = self._request(
            {"tenant_db_alias": "tenant-key", "group_id": "group-key"}
        )
        membership_patch, config_patch = self._mock_authorized_config(None)

        with (
            patch(
                "control.tenant_connections.connections", self._connections(databases)
            ),
            membership_patch,
            config_patch,
        ):
            result = ensure_tenant_connection_for_session(request)

        self.assertFalse(result)
        self.assertNotIn("tenant-key", databases)

    @override_settings(CENTRAL_DB_ALIAS="default", DATABASES={"default": {}})
    @patch("control.tenant_connections.lookup_user_id_from_request", return_value="user-key")
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
                "control.tenant_connections.connections", self._connections(databases)
            ),
            membership_patch,
            config_patch,
        ):
            result = ensure_tenant_connection_for_session(request)

        self.assertFalse(result)
        self.assertNotIn("tenant-key", databases)

    @override_settings(CENTRAL_DB_ALIAS="default", DATABASES={"default": {}})
    @patch("control.tenant_connections.lookup_user_id_from_request", return_value="user-key")
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
                "control.tenant_connections.connections", self._connections(databases)
            ),
            membership_patch,
            config_patch,
        ):
            result = ensure_tenant_connection_for_session(request)

        self.assertFalse(result)
        self.assertNotIn("tenant-key", databases)

    @override_settings(CENTRAL_DB_ALIAS="default", DATABASES={"default": {}})
    @patch("control.tenant_connections.lookup_user_id_from_request", return_value="user-key")
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
                "control.tenant_connections.connections", self._connections(databases)
            ),
            patch(
                "control.tenant_connections.UserGroupMap.objects.using",
                return_value=membership_using,
            ),
            patch(
                "control.tenant_connections.GroupDBConfig.objects.using",
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
    @patch("control.tenant_connections.lookup_user_id_from_request", return_value="user-key")
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
                "control.tenant_connections.connections", self._connections(databases)
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
            "control.tenant_connections.connections", self._connections(databases)
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

    @override_settings(CENTRAL_DB_ALIAS="default")
    @patch("control.middleware._set_threadlocal")
    @patch("control.middleware.ensure_tenant_connection_for_session")
    def test_middleware_keeps_central_flow_without_preparation(
        self, ensure_connection, set_threadlocal
    ):
        get_response = MagicMock(return_value="response")
        request = self._request({"tenant_db_alias": "default"})

        response = TenantMiddleware(get_response)(request)

        self.assertEqual(response, "response")
        ensure_connection.assert_not_called()
        set_threadlocal.assert_called_once_with("default", True, None)
        get_response.assert_called_once_with(request)

    @override_settings(CENTRAL_DB_ALIAS="default")
    @patch("control.middleware._set_threadlocal")
    @patch(
        "control.middleware.ensure_tenant_connection_for_session",
        return_value=True,
    )
    def test_middleware_reuses_registered_tenant_context(
        self, ensure_connection, set_threadlocal
    ):
        get_response = MagicMock(return_value="response")
        request = self._request(
            {"tenant_db_alias": "tenant-key", "group_id": "group-key"}
        )

        response = TenantMiddleware(get_response)(request)

        self.assertEqual(response, "response")
        ensure_connection.assert_called_once_with(request)
        set_threadlocal.assert_called_once_with(
            "tenant-key", False, "group-key"
        )

    @override_settings(CENTRAL_DB_ALIAS="default")
    @patch("control.middleware._set_threadlocal")
    @patch("control.middleware.ensure_tenant_connection_for_session")
    def test_middleware_prepares_before_setting_tenant_context(
        self, ensure_connection, set_threadlocal
    ):
        calls = []
        ensure_connection.side_effect = (
            lambda request: calls.append("prepare") or True
        )
        set_threadlocal.side_effect = (
            lambda *args: calls.append(("context",) + args)
        )
        get_response = MagicMock(return_value="response")
        request = self._request(
            {"tenant_db_alias": "tenant-key", "group_id": "group-key"}
        )

        response = TenantMiddleware(get_response)(request)

        self.assertEqual(response, "response")
        self.assertEqual(
            calls,
            ["prepare", ("context", "tenant-key", False, "group-key")],
        )

    def _assert_middleware_failure_is_safe(self):
        get_response = MagicMock(return_value="response")
        request = self._request(
            {
                "tenant_db_alias": "tenant-key",
                "db_key": "tenant-key",
                "group_id": "group-key",
                "group_uuid": "group-key",
                "roles": [],
            }
        )
        with (
            patch(
                "control.middleware.ensure_tenant_connection_for_session",
                return_value=False,
            ) as ensure_connection,
            patch("control.middleware._set_threadlocal") as set_threadlocal,
        ):
            response = TenantMiddleware(get_response)(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("control:dashboard"))
        self.assertEqual(request.session["tenant_db_alias"], "default")
        self.assertEqual(request.session["db_key"], "default")
        self.assertNotIn("group_id", request.session)
        self.assertNotIn("group_uuid", request.session)
        self.assertNotIn("tenant_candidates", request.session)
        set_threadlocal.assert_called_once_with("default", True, None)
        ensure_connection.assert_called_once_with(request)
        get_response.assert_not_called()

    @override_settings(CENTRAL_DB_ALIAS="default")
    def test_middleware_fails_closed_for_missing_config(self):
        self._assert_middleware_failure_is_safe()

    @override_settings(CENTRAL_DB_ALIAS="default")
    def test_middleware_fails_closed_for_incomplete_config(self):
        self._assert_middleware_failure_is_safe()

    @override_settings(CENTRAL_DB_ALIAS="default")
    def test_middleware_fails_closed_for_inactive_config(self):
        self._assert_middleware_failure_is_safe()

    @override_settings(CENTRAL_DB_ALIAS="default")
    @patch("control.middleware._set_threadlocal")
    @patch("control.middleware.ensure_tenant_connection_for_session")
    def test_middleware_ignores_request_payload_alias(
        self, ensure_connection, set_threadlocal
    ):
        get_response = MagicMock(return_value="response")
        request = self._request(
            {"tenant_db_alias": "default"},
            post_data={"tenant_db_alias": "untrusted-key"},
        )

        response = TenantMiddleware(get_response)(request)

        self.assertEqual(response, "response")
        ensure_connection.assert_not_called()
        set_threadlocal.assert_called_once_with("default", True, None)

    @override_settings(CENTRAL_DB_ALIAS="default")
    @patch("control.middleware._set_threadlocal")
    @patch("control.middleware.ensure_tenant_connection_for_session")
    def test_login_path_remains_available_with_stale_tenant_session(
        self, ensure_connection, set_threadlocal
    ):
        get_response = MagicMock(return_value="response")
        request = self.factory.get("/login/")
        request.session = {
            "tenant_db_alias": "tenant-key",
            "group_id": "group-key",
        }

        response = TenantMiddleware(get_response)(request)

        self.assertEqual(response, "response")
        ensure_connection.assert_not_called()
        set_threadlocal.assert_called_once_with("default", True, None)
        get_response.assert_called_once_with(request)

    @override_settings(CENTRAL_DB_ALIAS="default")
    @patch("control.middleware.logger")
    @patch("control.middleware._set_threadlocal")
    @patch(
        "control.middleware.ensure_tenant_connection_for_session",
        return_value=True,
    )
    def test_middleware_log_does_not_include_tenant_alias(
        self, _ensure_connection, _set_threadlocal, logger
    ):
        sensitive_alias = "sensitive-tenant-marker"
        request = self._request(
            {
                "tenant_db_alias": sensitive_alias,
                "group_id": "group-key",
            }
        )

        response = TenantMiddleware(lambda req: "response")(request)

        self.assertEqual(response, "response")
        logged_values = " ".join(
            str(value)
            for call in logger.method_calls
            for value in call.args
        )
        self.assertNotIn(sensitive_alias, logged_values)
        logger.debug.assert_called_with("MW: resolved tenant route")

    @override_settings(CENTRAL_DB_ALIAS="default")
    @patch("control.middleware._set_threadlocal")
    def test_fallback_does_not_set_unregistered_alias_from_session(
        self, set_threadlocal
    ):
        request = self._request({"tenant_db_alias": "unregistered-marker"})

        with patch("control.middleware._tlocal", SimpleNamespace()):
            response = EnsureTenantAliasMiddleware(
                lambda req: "response"
            )(request)

        self.assertEqual(response, "response")
        set_threadlocal.assert_not_called()

    @patch("control.middleware._set_threadlocal")
    def test_fallback_noops_when_tenant_context_is_already_set(
        self, set_threadlocal
    ):
        request = self._request({"tenant_db_alias": "session-marker"})
        context = SimpleNamespace(
            tenant_db_alias="registered-marker",
            is_central=False,
            tenant_id=None,
        )

        with patch("control.middleware._tlocal", context):
            response = EnsureTenantAliasMiddleware(
                lambda req: "response"
            )(request)

        self.assertEqual(response, "response")
        self.assertEqual(context.tenant_db_alias, "registered-marker")
        set_threadlocal.assert_not_called()

    @override_settings(CENTRAL_DB_ALIAS="default")
    @patch("control.middleware._set_threadlocal")
    def test_fallback_keeps_no_tenant_request_central(self, set_threadlocal):
        request = self._request({})

        with patch("control.middleware._tlocal", SimpleNamespace()):
            response = EnsureTenantAliasMiddleware(
                lambda req: current_db_alias()
            )(request)

        self.assertEqual(response, "default")
        set_threadlocal.assert_not_called()

    @override_settings(CENTRAL_DB_ALIAS="default")
    @patch("control.db_router.logger")
    @patch("control.middleware._set_threadlocal")
    def test_fallback_does_not_expose_unregistered_alias_to_router(
        self, set_threadlocal, _logger
    ):
        request = self._request({"tenant_db_alias": "unregistered-marker"})
        tenant_model = SimpleNamespace(
            _meta=SimpleNamespace(app_label="geoflow_ops")
        )

        with patch("control.middleware._tlocal", SimpleNamespace()):
            response = EnsureTenantAliasMiddleware(
                lambda req: TenantRouter().db_for_read(tenant_model)
            )(request)

        self.assertEqual(response, "default")
        set_threadlocal.assert_not_called()

    @override_settings(CENTRAL_DB_ALIAS="default")
    @patch(
        "control.db_router.current_db_alias",
        return_value="unregistered-marker",
    )
    def test_router_fails_closed_for_unregistered_tenant_alias(
        self, _current_alias
    ):
        tenant_model = SimpleNamespace(
            _meta=SimpleNamespace(app_label="geoflow_ops")
        )
        connection_handler = MagicMock()
        connection_handler.settings = {"default": {}}

        with (
            patch("control.db_router.connections", connection_handler),
            self.assertRaises(ImproperlyConfigured) as raised,
        ):
            TenantRouter().db_for_read(tenant_model)

        self.assertEqual(
            str(raised.exception),
            "Tenant database connection is unavailable.",
        )
        self.assertNotIn(
            "unregistered-marker",
            str(raised.exception),
        )

    @override_settings(CENTRAL_DB_ALIAS="default")
    @patch(
        "control.db_router.current_db_alias",
        return_value="registered-marker",
    )
    def test_router_uses_registered_tenant_alias(self, _current_alias):
        tenant_model = SimpleNamespace(
            _meta=SimpleNamespace(app_label="geoflow_ops")
        )
        connection_handler = MagicMock()
        connection_handler.settings = {
            "default": {},
            "registered-marker": {},
        }

        with patch("control.db_router.connections", connection_handler):
            result = TenantRouter().db_for_read(tenant_model)

        self.assertEqual(result, "registered-marker")
