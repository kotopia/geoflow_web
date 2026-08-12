from unittest.mock import patch

from django.test import SimpleTestCase

from control.services_acl import user_has_perm


class _Cursor:
    def __init__(self, *, role_status_supported):
        self.role_status_supported = role_status_supported
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
        if "FROM information_schema.columns" in self._last_sql:
            return (1,) if self.role_status_supported else None
        if "FROM user_group_map ugm" in self._last_sql:
            return (1,)
        return None


class _Connection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


class CanonicalAclRoleStatusTests(SimpleTestCase):
    def _evaluate(self, *, role_status_supported):
        cursor = _Cursor(role_status_supported=role_status_supported)
        with patch(
            "control.services_acl.connections",
            {"default": _Connection(cursor)},
        ):
            allowed = user_has_perm("user-key", "group-key", "contracts.view")
        permission_sql = next(
            sql for sql, _params in cursor.queries
            if "FROM user_group_map ugm" in sql
        )
        return allowed, permission_sql

    def test_active_role_is_required_when_status_column_exists(self):
        allowed, sql = self._evaluate(role_status_supported=True)
        self.assertTrue(allowed)
        self.assertIn("JOIN roles r ON r.id = ugm.role_id", sql)
        self.assertIn("lower(COALESCE(r.status, ''))='active'", sql)
        self.assertIn("ugm.status='active'", sql)

    def test_legacy_schema_without_role_status_preserves_existing_acl_query(self):
        allowed, sql = self._evaluate(role_status_supported=False)
        self.assertTrue(allowed)
        self.assertNotIn("JOIN roles r", sql)
        self.assertNotIn("r.status", sql)
        self.assertIn("ugm.status='active'", sql)
