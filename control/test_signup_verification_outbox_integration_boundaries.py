from inspect import getsource
from pathlib import Path
from unittest import TestCase

from control.services.signup_verification_signup_outbox_service import (
    create_signup_request_with_verification_outbox,
)


CONTROL_DIR = Path(__file__).resolve().parent


class SignupVerificationOutboxIntegrationBoundaryTests(TestCase):
    def test_signup_http_view_fails_closed_without_outbox(self):
        source = (CONTROL_DIR / "views_signup.py").read_text(encoding="utf-8")

        self.assertIn("signup_verification_outbox_enabled", source)
        self.assertIn("create_signup_request_with_verification_outbox", source)
        self.assertNotIn("create_signup_request(signup_data)", source)
        self.assertIn("if not signup_available:", source)
        self.assertIn("status=200 if signup_available else 503", source)
        self.assertNotIn("send_mail", source)
        self.assertNotIn("issue_signup_email_verification_token", source)
        self.assertNotIn("submit_signup_with_email_verification", source)
        for sensitive_field in (
            '"email"',
            '"password"',
            '"password_confirm"',
            '"contact_phone"',
            '"organization_name"',
            '"signup_purpose"',
            '"invitation_code"',
        ):
            self.assertIn(sensitive_field, source)
        self.assertIn(
            '@sensitive_variables("cleaned", "signup_data")',
            source,
        )

    def test_available_signup_message_mentions_email_verification(self):
        source = (CONTROL_DIR / "views_signup.py").read_text(encoding="utf-8")

        self.assertIn("이메일 인증을 완료한 후", source)
        self.assertIn("관리자 승인을 기다려 주세요", source)

    def test_signup_orchestrator_does_not_import_mail_or_token_services(self):
        source = getsource(create_signup_request_with_verification_outbox)

        for forbidden in (
            "send_mail",
            "verification_link",
            "issue_signup_email_verification_token",
            "key_ring",
            "raw_token",
        ):
            self.assertNotIn(forbidden, source)

    def test_outbox_feature_flag_defaults_disabled_for_safe_rollout(self):
        feature_path = (
            CONTROL_DIR
            / "services/signup_verification_outbox_feature.py"
        )
        source = feature_path.read_text(encoding="utf-8")

        self.assertIn("ENABLE_SIGNUP_EMAIL_VERIFICATION_OUTBOX", source)
        self.assertIn("return False", source)
        self.assertNotIn("raw_token", source)

    def test_management_command_is_bounded_and_not_a_daemon(self):
        command_path = (
            CONTROL_DIR
            / "management/commands/process_signup_verification_outbox.py"
        )
        source = command_path.read_text(encoding="utf-8")

        self.assertIn('parser.add_argument("--limit"', source)
        self.assertIn("while processed < limit", source)
        self.assertNotIn("while True", source)
        self.assertNotIn("sleep(", source)
        self.assertNotIn("recipient", source.lower())
        self.assertNotIn("token=", source.lower())
