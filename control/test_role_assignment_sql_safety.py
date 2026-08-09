from pathlib import Path
import unittest


class RoleAssignmentSQLSafetyTests(unittest.TestCase):
    def test_password_hash_like_wildcards_are_escaped_for_bound_parameters(self):
        source = Path(__file__).with_name("views_users_admin.py").read_text(encoding="utf-8")

        expected_patterns = (
            "u.password_hash LIKE 'pbkdf2_sha256$%%'",
            "u.password_hash LIKE 'bcrypt_sha256$%%'",
            "u.password_hash LIKE '$2a$%%'",
            "u.password_hash LIKE '$2b$%%'",
            "u.password_hash LIKE '$2y$%%'",
        )
        for pattern in expected_patterns:
            self.assertIn(pattern, source)

        # Psycopg parameter binding treats '%' as part of its placeholder syntax.
        # These LIKE wildcards must therefore remain doubled in SQL that also
        # supplies a parameter sequence to cursor.execute().
        self.assertEqual(source.count("u.password_hash LIKE"), len(expected_patterns))


if __name__ == "__main__":
    unittest.main()
