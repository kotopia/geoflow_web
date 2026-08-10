from contextlib import nullcontext
from inspect import unwrap
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from django.test import RequestFactory, SimpleTestCase
from django.urls import resolve

from control import views_user_assignment


CONTROL_DIR = Path(__file__).resolve().parent


class _Cursor:
    def __init__(self, results):
        self.results = iter(results)
        self.current = None
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        self.executed.append((normalized, params or []))
        self.current = next(self.results)

    def fetchone(self):
        return self.current


class _Connection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


class UserAssignmentSchemaCompatibilityTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user_id = UUID(int=31)
        self.request = self.factory.post(
            "/control/mgmt/users/assign/",
            {"group_id": "group-key", "role_id": "role-key"},
        )

    def _run(self, cursor):
        with patch.object(
            views_user_assignment,
            "connections",
            {"default": _Connection(cursor)},
        ), patch.object(
            views_user_assignment.transaction,
            "atomic",
            return_value=nullcontext(),
        ), patch.object(views_user_assignment.messages, "success") as success:
            response = unwrap(views_user_assignment.users_assign_group_admin)(
                self.request,
                self.user_id,
            )
        return response, success

    def test_route_uses_schema_compatible_assignment_handler(self):
        match = resolve(
            f"/control/mgmt/users/{self.user_id}/assign/"
        )
        self.assertIs(match.func, views_user_assignment.users_assign_group_admin)

    def test_new_membership_uses_lock_update_then_insert_without_on_conflict(self):
        cursor = _Cursor(
            [
                (str(self.user_id), "group-key", "role-key"),
                None,
                ("membership-key",),
            ]
        )
        response, success = self._run(cursor)

        self.assertEqual(response.status_code, 302)
        success.assert_called_once()
        self.assertEqual(len(cursor.executed), 3)
        self.assertIn("FOR UPDATE OF u, g, r", cursor.executed[0][0])
        self.assertIn("UPDATE user_group_map", cursor.executed[1][0])
        self.assertIn("INSERT INTO user_group_map", cursor.executed[2][0])
        self.assertTrue(
            all("ON CONFLICT" not in sql for sql, _ in cursor.executed)
        )
        self.assertTrue(
            all("gen_random_uuid" not in sql for sql, _ in cursor.executed)
        )

    def test_existing_membership_updates_without_duplicate_insert(self):
        cursor = _Cursor(
            [
                (str(self.user_id), "group-key", "role-key"),
                ("membership-key",),
            ]
        )
        response, success = self._run(cursor)

        self.assertEqual(response.status_code, 302)
        success.assert_called_once()
        self.assertEqual(len(cursor.executed), 2)
        self.assertIn("UPDATE user_group_map", cursor.executed[1][0])

    def test_assignment_keeps_activation_and_password_hash_gates(self):
        source = (CONTROL_DIR / "views_user_assignment.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("u.is_active=TRUE", source)
        self.assertIn("u.email_verified=TRUE", source)
        self.assertIn("u.password_hash IS NOT NULL", source)
        self.assertIn("lower(COALESCE(g.status, ''))='active'", source)
        self.assertIn("pbkdf2_sha256$%%", source)
        self.assertNotIn("ON CONFLICT", source)
        self.assertNotIn("gen_random_uuid", source)
