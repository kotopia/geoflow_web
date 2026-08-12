from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from control.gf_authz.services import gf_load_user_context


class _Cursor:
    def __init__(self):
        self.queries = []
        self._last_sql = ""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self._last_sql = " ".join(str(sql).split())
        self.queries.append((self._last_sql, params))

    def fetchone(self):
        if "SELECT id FROM public.users" in self._last_sql:
            return ("user-key",)
        return None

    def fetchall(self):
        if "SELECT r.code" in self._last_sql:
            return [("member",)]
        if "SELECT DISTINCT p.code" in self._last_sql:
            return [("contracts.view",)]
        return []


class _Connection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


@override_settings(GF_AUTHZ_TABLES={}, GF_AUTHZ_CENTRAL_ALIAS="default")
class ActiveRoleMappingAuthorizationTests(SimpleTestCase):
    def test_effective_roles_and_permissions_require_active_mapping(self):
        cursor = _Cursor()
        request = SimpleNamespace(
            session={
                "group_id": "group-key",
                "tenant_db_alias": "tenant_db",
                "scope": "tenant",
            },
            user=SimpleNamespace(email="account@example.invalid"),
        )

        with patch(
            "control.gf_authz.services.connections",
            {"default": _Connection(cursor)},
        ):
            context = gf_load_user_context(request)

        mapping_queries = [
            sql for sql, _params in cursor.queries
            if "FROM public.user_group_map ur" in sql
        ]
        self.assertEqual(len(mapping_queries), 2)
        for sql in mapping_queries:
            self.assertIn("ur.status = 'active'", sql)
            self.assertNotIn("status IS NULL", sql)

        self.assertEqual(context["tenant_id"], "group-key")
        self.assertEqual(set(context["roles"]), {"member"})
        self.assertEqual(set(context["perms"]), {"contracts.view"})
