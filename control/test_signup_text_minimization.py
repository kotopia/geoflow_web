from pathlib import Path
from unittest import TestCase


CONTROL_DIR = Path(__file__).resolve().parent


class SignupTextMinimizationTests(TestCase):
    def test_signup_purpose_warns_against_sensitive_identifiers(self):
        source = (CONTROL_DIR / "templates/control/signup.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("주민등록번호", source)
        self.assertIn("민감정보", source)
        self.assertIn("고유식별정보", source)

    def test_admin_decision_note_warns_against_secret_or_sensitive_data(self):
        source = (
            CONTROL_DIR / "templates/control/signup_review_detail_admin.html"
        ).read_text(encoding="utf-8")
        self.assertIn("주민등록번호", source)
        self.assertIn("비밀번호", source)
        self.assertIn("인증 토큰", source)
