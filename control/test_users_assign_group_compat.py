from django.test import SimpleTestCase

from control.views_users_admin import _assign_user_group_membership


class _FakeCursor:
    def __init__(self, fetchone_results):
        self._fetchone_results = iter(fetchone_results)
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((" ".join(sql.split()), list(params or [])))

    def fetchone(self):
        return next(self._fetchone_results)


class UserGroupMembershipCompatibilityTests(SimpleTestCase):
    def test_existing_membership_updates_without_on_conflict(self):
        cursor = _FakeCursor([
            ("user-id",),
            ("membership-id",),
        ])

        assigned = _assign_user_group_membership(
            cursor,
            user_id="user-id",
            group_id="group-id",
            role_id="role-id",
        )

        self.assertTrue(assigned)
        self.assertEqual(len(cursor.calls), 2)
        self.assertIn("FOR UPDATE OF u", cursor.calls[0][0])
        self.assertIn("UPDATE user_group_map", cursor.calls[1][0])
        self.assertNotIn(
            "ON CONFLICT",
            " ".join(sql for sql, _params in cursor.calls),
        )

    def test_missing_membership_inserts_after_update_miss(self):
        cursor = _FakeCursor([
            ("user-id",),
            None,
            ("membership-id",),
        ])

        assigned = _assign_user_group_membership(
            cursor,
            user_id="user-id",
            group_id="group-id",
            role_id="role-id",
        )

        self.assertTrue(assigned)
        self.assertEqual(len(cursor.calls), 3)
        self.assertIn("UPDATE user_group_map", cursor.calls[1][0])
        self.assertIn("INSERT INTO user_group_map", cursor.calls[2][0])
        self.assertEqual(cursor.calls[2][1], ["user-id", "group-id", "role-id"])

    def test_ineligible_user_does_not_mutate_membership(self):
        cursor = _FakeCursor([None])

        assigned = _assign_user_group_membership(
            cursor,
            user_id="user-id",
            group_id="group-id",
            role_id="role-id",
        )

        self.assertFalse(assigned)
        self.assertEqual(len(cursor.calls), 1)
        self.assertIn("u.is_active=TRUE", cursor.calls[0][0])
        self.assertIn("u.email_verified=TRUE", cursor.calls[0][0])
