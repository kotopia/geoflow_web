from contextlib import nullcontext
from inspect import unwrap
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from control.views_user_assignment import users_assign_group_admin


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
        if self._last_sql.startswith("SELECT u.id::text"):
            return ("user-key", "group-key", "role-key")
        if self._last_sql.startswith("UPDATE user_group_map"):
            return ("mapping-key",)
        return None


class _Connection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


class DirectRoleAssignmentStatusTests(SimpleTestCase):
    def _run_assignment(self, *, role_status_supported):
        cursor = _Cursor(role_status_supported=role_status_supported)
        request = SimpleNamespace(
            method="POST",
            POST={"group_id": "group-key", "role_id": "role-key"},
        )
        raw_view = unwrap(users_assign_group_admin)

        with (
            patch(
                "control.views_user_assignment.connections",
                {"default": _Connection(cursor)},
            ),
            patch(
                "control.views_user_assignment.transaction.atomic",
                return_value=nullcontext(),
            ),
            patch("control.views_user_assignment.messages.success"),
            patch("control.views_user_assignment.messages.error"),
            patch(
                "control.views_user_assignment.redirect",
                return_value="redirected",
            ),
        ):
            response = raw_view(request, "user-key")

        eligibility_sql = next(
            sql
            for sql, _params in cursor.queries
            if sql.startswith("SELECT u.id::text")
        )
        return response, eligibility_sql

    def test_direct_assignment_requires_active_role_when_status_column_exists(self):
        response, sql = self._run_assignment(role_status_supported=True)

        self.assertEqual(response, "redirected")
        self.assertIn("lower(COALESCE(r.status, ''))='active'", sql)
        self.assertIn("FOR UPDATE OF u, g, r", sql)

    def test_legacy_schema_without_role_status_preserves_assignment_path(self):
        response, sql = self._run_assignment(role_status_supported=False)

        self.assertEqual(response, "redirected")
        self.assertNotIn("r.status", sql)
        self.assertIn("JOIN roles r ON r.id=%s", sql)
        self.assertIn("FOR UPDATE OF u, g, r", sql)
