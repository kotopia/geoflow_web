from base64 import urlsafe_b64encode
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from control.services.signup_service import SignupRequestInput
from control.services.signup_submission_runtime import (
    SignupSubmissionOutcome,
    load_signup_email_verification_ttl,
    submit_signup_with_email_verification,
)
from control.services.signup_verification_email_delivery import (
    SignupVerificationEmailDeliveryError,
)
from control.services.signup_verification_service import (
    EmailVerificationConfigurationError,
)


class SignupSubmissionRuntimeTests(TestCase):
    def setUp(self):
        self.data = SignupRequestInput(
            email="applicant@example.com",
            password="raw-password-must-not-appear",
            name_display="신청자",
            contact_phone="010-0000-0000",
            organization_name="기관",
            signup_purpose="업무 활용",
            terms_agreed=True,
            privacy_agreed=True,
        )
        self.raw_key = b"k" * 32
        self.settings = SimpleNamespace(
            SIGNUP_EMAIL_VERIFICATION_ACTIVE_KEY_ID="current",
            SIGNUP_EMAIL_VERIFICATION_HMAC_KEYS={
                "current": urlsafe_b64encode(self.raw_key).decode("ascii"),
            },
            SIGNUP_EMAIL_VERIFICATION_TTL_SECONDS=7200,
            DEFAULT_FROM_EMAIL="sender@example.com",
        )
        self.pending = SimpleNamespace(
            signup_request_id="request-reference",
            token=f"v1.current.{('s' * 43)}",
            expires_at=datetime(2026, 8, 6, 14, 0, tzinfo=timezone.utc),
        )

    def test_valid_config_persists_before_delivery_and_returns_no_secret(self):
        calls = []

        def create_pending(data, *, ttl, key_ring):
            calls.append("persist")
            self.assertIs(data, self.data)
            self.assertEqual(ttl, timedelta(hours=2))
            self.assertEqual(key_ring.active_key_id, "current")
            self.assertEqual(key_ring.active_key(), self.raw_key)
            return self.pending

        def build_link(url, token):
            calls.append("link")
            self.assertEqual(url, "https://example.com/signup/verify/")
            self.assertEqual(token, self.pending.token)
            return f"{url}#token={token}"

        def deliver(**values):
            calls.append("deliver")
            self.assertEqual(values["to_email"], self.data.email)
            self.assertIn(self.pending.token, values["verification_link"])
            self.assertEqual(values["expires_at"], self.pending.expires_at)

        outcome = submit_signup_with_email_verification(
            self.data,
            verification_url="https://example.com/signup/verify/",
            settings_obj=self.settings,
            create_pending=create_pending,
            link_builder=build_link,
            deliver=deliver,
        )

        self.assertEqual(calls, ["persist", "link", "deliver"])
        self.assertEqual(outcome, SignupSubmissionOutcome(True))
        self.assertNotIn(self.pending.token, repr(outcome))
        self.assertNotIn(self.data.email, repr(outcome))

    @patch("control.services.signup_submission_runtime.logger")
    def test_delivery_failure_keeps_committed_signup_and_logs_no_secret(
        self,
        logger,
    ):
        create_pending = MagicMock(return_value=self.pending)
        deliver = MagicMock(
            side_effect=SignupVerificationEmailDeliveryError("sanitized")
        )

        outcome = submit_signup_with_email_verification(
            self.data,
            verification_url="https://example.com/signup/verify/",
            settings_obj=self.settings,
            create_pending=create_pending,
            link_builder=lambda url, token: f"{url}#token={token}",
            deliver=deliver,
        )

        self.assertEqual(outcome, SignupSubmissionOutcome(False))
        create_pending.assert_called_once()
        logger.warning.assert_called_once_with(
            "SIGNUP: verification email delivery failed"
        )
        self.assertNotIn(self.pending.token, repr(logger.mock_calls))
        self.assertNotIn(self.data.email, repr(logger.mock_calls))
        self.assertNotIn(self.data.password, repr(logger.mock_calls))

    def test_invalid_verification_url_fails_before_signup_persistence(self):
        create_pending = MagicMock()

        for verification_url in (
            "/signup/verify/",
            "https://example.com/signup/verify/#preexisting",
        ):
            with self.subTest(verification_url=verification_url):
                with self.assertRaises(ValueError):
                    submit_signup_with_email_verification(
                        self.data,
                        verification_url=verification_url,
                        settings_obj=self.settings,
                        create_pending=create_pending,
                    )

        create_pending.assert_not_called()

    def test_missing_or_out_of_range_ttl_fails_before_signup_persistence(self):
        invalid_values = (None, True, 0, 59, 604_801, "7200")
        create_pending = MagicMock()

        for value in invalid_values:
            with self.subTest(value=value):
                settings_obj = SimpleNamespace(
                    SIGNUP_EMAIL_VERIFICATION_ACTIVE_KEY_ID="current",
                    SIGNUP_EMAIL_VERIFICATION_HMAC_KEYS={
                        "current": urlsafe_b64encode(self.raw_key).decode("ascii"),
                    },
                    SIGNUP_EMAIL_VERIFICATION_TTL_SECONDS=value,
                )
                with self.assertRaises(EmailVerificationConfigurationError):
                    submit_signup_with_email_verification(
                        self.data,
                        verification_url="https://example.com/signup/verify/",
                        settings_obj=settings_obj,
                        create_pending=create_pending,
                    )

        create_pending.assert_not_called()

    def test_ttl_loader_accepts_bounded_integer_seconds(self):
        self.assertEqual(
            load_signup_email_verification_ttl(settings_obj=self.settings),
            timedelta(hours=2),
        )

    @patch(
        "control.services.signup_submission_runtime."
        "load_signup_email_verification_key_ring",
        side_effect=EmailVerificationConfigurationError("invalid key config"),
    )
    def test_key_configuration_failure_precedes_signup_persistence(
        self,
        _load_key_ring,
    ):
        create_pending = MagicMock()

        with self.assertRaises(EmailVerificationConfigurationError):
            submit_signup_with_email_verification(
                self.data,
                verification_url="https://example.com/signup/verify/",
                settings_obj=self.settings,
                create_pending=create_pending,
            )

        create_pending.assert_not_called()

    def test_synchronous_delivery_fails_before_signup_when_outbox_enabled(self):
        settings_obj = SimpleNamespace(
            ENABLE_SIGNUP_EMAIL_VERIFICATION_OUTBOX=True,
        )
        create_pending = MagicMock()
        deliver = MagicMock()

        with self.assertRaises(EmailVerificationConfigurationError):
            submit_signup_with_email_verification(
                self.data,
                verification_url="https://example.invalid/signup/verify/",
                settings_obj=settings_obj,
                create_pending=create_pending,
                deliver=deliver,
            )

        create_pending.assert_not_called()
        deliver.assert_not_called()
