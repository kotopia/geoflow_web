from pathlib import Path
import unittest


class RoleAssignmentSQLSafetyTests(unittest.TestCase):
    def _source(self) -> str:
        return Path(__file__).with_name("views_users_admin.py").read_text(encoding="utf-8")

    def _template(self) -> str:
        return (
            Path(__file__).parent
            / "templates"
            / "control"
            / "users_detail_admin.html"
        ).read_text(encoding="utf-8")

    def test_password_hash_like_wildcards_are_escaped_for_bound_parameters(self):
        source = self._source()

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

    def test_role_assignment_remains_guarded_by_onboarding_readiness(self):
        source = self._source()
        required_guards = (
            "lower(COALESCE(g.status, ''))='active'",
            "u.is_active=TRUE",
            "u.email_verified=TRUE",
            "u.password_hash IS NOT NULL",
            "length(trim(u.password_hash)) > 0",
            "RETURNING id",
            "assigned = cur.fetchone() is not None",
        )
        for guard in required_guards:
            self.assertIn(guard, source)

    def test_failed_guard_does_not_report_assignment_success(self):
        source = self._source()
        self.assertIn("if not assigned:", source)
        self.assertIn("활성화된 사용자와 유효한 그룹/역할만 지정할 수 있습니다.", source)
        failure_index = source.index("if not assigned:")
        success_index = source.index('messages.success(request, "그룹/역할이 지정되었습니다.")')
        self.assertLess(failure_index, success_index)

    def test_admin_ui_does_not_present_tenant_join_history_as_signup_status(self):
        template = self._template()
        self.assertIn("중앙 회원가입 절차", template)
        self.assertIn("이메일 인증", template)
        self.assertIn("계정 승인", template)
        self.assertIn("테넌트 합류 요청", template)
        self.assertIn("중앙 회원가입/가입심사 상태와 별개", template)
        self.assertNotIn('<h6 class="card-title">합류 요청</h6>', template)


if __name__ == "__main__":
    unittest.main()
