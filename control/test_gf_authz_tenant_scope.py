import unittest
from types import SimpleNamespace
from unittest.mock import patch

from control.gf_authz import services


class _ExplodingConnections:
    def __getitem__(self, alias):
        raise AssertionError("central DB must not be consulted without tenant scope")


class _FakeCursor:
    def __init__(self):
        self.calls = []
        self._fetchall_index = 0

    def execute(self, sql, params):
        self.calls.append((" ".join(sql.split()), list(params)))

    def fetchone(self):
        return ("central-user-1",)

    def fetchall(self):
        rows = [
            [("viewer",)],
            [("maps.view",)],
        ][self._fetchall_index]
        self._fetchall_index += 1
        return rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


class _FakeConnections:
    def __init__(self, cursor):
        self._connection = _FakeConnection(cursor)

    def __getitem__(self, alias):
        if alias != "default":
            raise AssertionError(f"unexpected database alias: {alias}")
        return self._connection


class GFAuthzTenantScopeTests(unittest.TestCase):
    def _request(self, session):
        return SimpleNamespace(
            session=session,
            user=SimpleNamespace(
                email="member@example.com",
                username="member@example.com",
            ),
        )

    def test_missing_group_scope_fails_closed_without_db_lookup(self):
        request = self._request(
            {"tenant_db_alias": "cheonan_db", "scope": "tenant"}
        )
        with patch.object(services, "connections", _ExplodingConnections()):
            context = services.gf_load_user_context(request)

        self.assertEqual(
            context,
            {"tenant_id": None, "roles": [], "perms": [], "project_ids": []},
        )

    def test_group_uuid_is_an_explicit_group_identifier(self):
        request = self._request({"group_uuid": "group-a"})
        self.assertEqual(services._resolve_group_id(request), "group-a")

    def test_stale_group_on_central_scope_fails_closed_without_db_lookup(self):
        fake_settings = SimpleNamespace(
            GF_AUTHZ_CENTRAL_ALIAS="default",
            GF_AUTHZ_TABLES={},
        )
        request = self._request(
            {
                "group_id": "group-a",
                "tenant_db_alias": "default",
                "scope": "central",
            }
        )
        with patch.object(services, "connections", _ExplodingConnections()), patch.object(
            services, "settings", fake_settings
        ):
            context = services.gf_load_user_context(request)

        self.assertEqual(
            context,
            {"tenant_id": None, "roles": [], "perms": [], "project_ids": []},
        )

    def test_group_without_tenant_alias_fails_closed_without_db_lookup(self):
        fake_settings = SimpleNamespace(
            GF_AUTHZ_CENTRAL_ALIAS="default",
            GF_AUTHZ_TABLES={},
        )
        request = self._request({"group_id": "group-a", "scope": "tenant"})
        with patch.object(services, "connections", _ExplodingConnections()), patch.object(
            services, "settings", fake_settings
        ):
            context = services.gf_load_user_context(request)

        self.assertEqual(
            context,
            {"tenant_id": None, "roles": [], "perms": [], "project_ids": []},
        )

    def test_non_tenant_scope_marker_fails_closed_without_db_lookup(self):
        fake_settings = SimpleNamespace(
            GF_AUTHZ_CENTRAL_ALIAS="default",
            GF_AUTHZ_TABLES={},
        )
        request = self._request(
            {
                "group_id": "group-a",
                "tenant_db_alias": "cheonan_db",
                "scope": "central",
            }
        )
        with patch.object(services, "connections", _ExplodingConnections()), patch.object(
            services, "settings", fake_settings
        ):
            context = services.gf_load_user_context(request)

        self.assertEqual(
            context,
            {"tenant_id": None, "roles": [], "perms": [], "project_ids": []},
        )

    def test_role_and_permission_queries_are_group_scoped(self):
        cursor = _FakeCursor()
        fake_settings = SimpleNamespace(
            GF_AUTHZ_CENTRAL_ALIAS="default",
            GF_AUTHZ_TABLES={},
        )
        request = self._request(
            {
                "group_id": "group-a",
                "tenant_db_alias": "cheonan_db",
                "scope": "tenant",
            }
        )

        with patch.object(services, "connections", _FakeConnections(cursor)), patch.object(
            services, "settings", fake_settings
        ):
            context = services.gf_load_user_context(request)

        self.assertEqual(context["tenant_id"], "group-a")
        self.assertEqual(set(context["roles"]), {"viewer"})
        self.assertEqual(set(context["perms"]), {"maps.view"})

        scoped_calls = [
            (sql, params)
            for sql, params in cursor.calls
            if "user_group_map" in sql
        ]
        self.assertEqual(len(scoped_calls), 2)
        for sql, params in scoped_calls:
            self.assertIn("ur.group_id = %s", sql)
            self.assertEqual(params[-1], "group-a")


if __name__ == "__main__":
    unittest.main()
