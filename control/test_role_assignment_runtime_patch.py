from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.ops.patch_role_assignment_legacy_runtime import patch_file, transform_source


LEGACY_SOURCE = '''from types import SimpleNamespace

@require_central_admin
@csrf_protect
def users_assign_group_admin(request, user_id):
    if request.method != "POST":
        return redirect("control:users_detail_admin", user_id=user_id)
    group_id = request.POST.get("group_id")
    role_id = request.POST.get("role_id")
    assigned = False
    with connections["default"].cursor() as cur:
        cur.execute(
            """
            INSERT INTO user_group_map(
                id, user_id, group_id, role_id, status, created_at, updated_at
            )
            SELECT gen_random_uuid(), u.id, g.id, r.id, 'active', now(), now()
              FROM users u
              JOIN groups g ON g.id=%s
              JOIN roles r ON r.id=%s
             WHERE u.id=%s
               AND u.is_active=TRUE
               AND u.email_verified=TRUE
               AND u.password_hash IS NOT NULL
               AND length(trim(u.password_hash)) > 0
               AND u.password_hash LIKE 'pbkdf2_sha256$%%'
            ON CONFLICT (user_id, group_id)
            DO UPDATE SET role_id=EXCLUDED.role_id
            RETURNING id
            """,
            [group_id, role_id, str(user_id)],
        )
        assigned = cur.fetchone() is not None
    if not assigned:
        return redirect("control:users_detail_admin", user_id=user_id)
    return redirect("control:users_detail_admin", user_id=user_id)


@login_required
def dashboard(request):
    pass
'''


class RoleAssignmentRuntimePatchTests(unittest.TestCase):
    def test_transform_replaces_only_legacy_assignment_contract(self):
        updated, changed = transform_source(LEGACY_SOURCE)
        self.assertTrue(changed)
        self.assertIn("from uuid import uuid4", updated)
        self.assertIn('with transaction.atomic(using="default"):', updated)
        self.assertIn("FOR UPDATE OF u, g, r", updated)
        self.assertIn("UPDATE user_group_map", updated)
        self.assertIn("INSERT INTO user_group_map(", updated)
        self.assertIn("str(uuid4())", updated)
        self.assertIn("pbkdf2_sha256$%%", updated)
        self.assertNotIn("ON CONFLICT (user_id, group_id)", updated)
        self.assertNotIn("gen_random_uuid()", updated)
        self.assertIn("@login_required\ndef dashboard", updated)

    def test_transform_is_idempotent_after_safe_patch(self):
        updated, changed = transform_source(LEGACY_SOURCE)
        self.assertTrue(changed)
        second, second_changed = transform_source(updated)
        self.assertFalse(second_changed)
        self.assertEqual(second, updated)

    def test_transform_fails_closed_on_unreviewed_function_shape(self):
        unexpected = LEGACY_SOURCE.replace("RETURNING id", "SELECT 1")
        with self.assertRaises(ValueError):
            transform_source(unexpected)

    def test_patch_file_preserves_surrounding_source_and_is_repeatable(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "views_users_admin.py"
            path.write_text(LEGACY_SOURCE, encoding="utf-8")
            self.assertTrue(patch_file(path))
            patched = path.read_text(encoding="utf-8")
            self.assertIn("from types import SimpleNamespace", patched)
            self.assertIn("@login_required\ndef dashboard", patched)
            self.assertFalse(patch_file(path))
            self.assertEqual(path.read_text(encoding="utf-8"), patched)


if __name__ == "__main__":
    unittest.main()
