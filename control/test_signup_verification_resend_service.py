from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from inspect import getsource
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from control.services.signup_verification_email_delivery import (
    SignupVerificationEmailDeliveryError,
    send_signup_email_verification_email,
)
from control.services.signup_verification_resend_service import (
    CentralSignupVerificationResendRepository,
    PendingSignupVerificationResend,
    SignupVerificationResendTarget,
    prepare_signup_email_verification_resend,
)
from control.services.signup_verification_service import (
    EmailVerificationConfigurationError,
)


class SignupVerificationResendTests(TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)
        self.resend_repository = MagicMock()
        self.resend_repository.alias = "central"
        self.resend_repository.lock_eligible_target.return_value = (
            SignupVerificationResendTarget(
                signup_request_id="request-reference",
                email="Applicant@Example.com",
            )
        )
        self.token_repository = MagicMock()
        self.token_repository.alias = "central"
        self.issued = SimpleNamespace(
            token=f"v1.current.{('s' * 43)}",
            expires_at=self.now + timedelta(hours=2),
        )

    def _prepare(self, **overrides):
        values = {
            "email": " Applicant@Example.com ",
            "ttl": timedelta(hours=2),
            "cooldown": timedelta(minutes=15),
            "key_ring": object(),
            "alias": "central",
            "resend_repository": self.resend_repository,
            "token_repository": self.token_repository,
            "atomic_context": nullcontext(),
            "clock": lambda: self.now,
            "token_factory": lambda _size: "s" * 43,
        }
        values.update(overrides)
        return prepare_signup_email_verification_resend(**values)

    @patch(
        "control.services.signup_verification_resend_service."
        "issue_signup_email_verification_token"
    )
    def test_eligible_target_issues_fresh_digest_inside_locked_transaction(
        self,
        issue,
    ):
        issue.return_value = self.issued

        pending = self._prepare()

        self.assertEqual(
            pending,
            PendingSignupVerificationResend(
                signup_request_id="request-reference",
                email="Applicant@Example.com",
                token=self.issued.token,
                expires_at=self.issued.expires_at,
            ),
        )
        self.resend_repository.lock_eligible_target.assert_called_once_with(
            email="applicant@example.com",
            recent_token_cutoff=self.now - timedelta(minutes=15),
        )
        issued_values = issue.call_args.kwargs
        self.assertEqual(issued_values["signup_request_id"], "request-reference")
        self.assertIs(issued_values["repository"], self.token_repository)
        self.assertNotIn("email", issued_values)
        self.assertNotIn(self.issued.token, repr(pending))
        self.assertNotIn("Applicant@Example.com", repr(pending))
        self.assertNotIn("request-reference", repr(pending))

    @patch(
        "control.services.signup_verification_resend_service."
        "issue_signup_email_verification_token"
    )
    def test_unknown_ineligible_or_cooldown_target_returns_same_none(self, issue):
        self.resend_repository.lock_eligible_target.return_value = None

        self.assertIsNone(self._prepare())

        issue.assert_not_called()
        self.token_repository.create_digest.assert_not_called()

    @patch(
        "control.services.signup_verification_resend_service."
        "issue_signup_email_verification_token"
    )
    def test_alias_mismatch_rejects_before_lookup_or_token_write(self, issue):
        self.token_repository.alias = "tenant"

        with self.assertRaises(EmailVerificationConfigurationError):
            self._prepare()

        self.resend_repository.lock_eligible_target.assert_not_called()
        issue.assert_not_called()

    def test_non_positive_ttl_or_cooldown_rejects_before_lookup(self):
        invalid_values = (
            {"ttl": timedelta(0)},
            {"cooldown": timedelta(0)},
            {"cooldown": timedelta(seconds=-1)},
        )
        for overrides in invalid_values:
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    self._prepare(**overrides)

        self.resend_repository.lock_eligible_target.assert_not_called()

    def test_repository_uses_row_lock_and_recent_issue_cooldown(self):
        source = getsource(
            CentralSignupVerificationResendRepository.lock_eligible_target
        )
        for contract in (
            "lower(signup_user.email)=lower(%s)",
            "signup_request.status='pending_email_verification'",
            "signup_user.email_verified=FALSE",
            "signup_user.is_active=FALSE",
            "FOR UPDATE OF signup_request",
            "signup_email_verification_tokens",
            "created_at > %s",
        ):
            self.assertIn(contract, source)
        for forbidden in (
            "password_hash",
            "token_digest",
            "join_requests",
            "user_group_map",
            "employee_profile",
        ):
            self.assertNotIn(forbidden, source)


    @patch(
        "control.services.signup_verification_resend_service."
        "signup_verification_outbox_enabled",
        return_value=True,
    )
    def test_direct_resend_is_disabled_before_repository_when_outbox_enabled(self, _enabled):
        with self.assertRaises(EmailVerificationConfigurationError):
            self._prepare()

        self.resend_repository.lock_eligible_target.assert_not_called()
        self.token_repository.revoke_unconsumed.assert_not_called()
        self.token_repository.create_digest.assert_not_called()


class SignupVerificationEmailDeliveryTests(TestCase):
    def setUp(self):
        self.token = f"v1.current.{('s' * 43)}"
        self.link = f"https://example.com/signup/verify/#token={self.token}"
        self.expires_at = datetime(2026, 8, 6, 14, 0, tzinfo=timezone.utc)

    def test_delivery_sends_one_message_only_to_delivery_boundary(self):
        sender = MagicMock(return_value=1)

        send_signup_email_verification_email(
            to_email="applicant@example.com",
            verification_link=self.link,
            expires_at=self.expires_at,
            mail_sender=sender,
            settings_obj=SimpleNamespace(DEFAULT_FROM_EMAIL="sender@example.com"),
        )

        args = sender.call_args.args
        self.assertIn(self.link, args[1])
        self.assertEqual(args[2], "sender@example.com")
        self.assertEqual(args[3], ["applicant@example.com"])
        self.assertEqual(sender.call_args.kwargs, {"fail_silently": False})

    def test_delivery_failure_is_sanitized(self):
        sender = MagicMock(side_effect=RuntimeError(self.link))

        with self.assertRaises(SignupVerificationEmailDeliveryError) as raised:
            send_signup_email_verification_email(
                to_email="applicant@example.com",
                verification_link=self.link,
                expires_at=self.expires_at,
                mail_sender=sender,
            )

        self.assertNotIn(self.token, str(raised.exception))
        self.assertNotIn("applicant@example.com", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertTrue(raised.exception.__suppress_context__)

    def test_delivery_rejects_non_absolute_link_before_mail_backend(self):
        sender = MagicMock()

        with self.assertRaises(ValueError):
            send_signup_email_verification_email(
                to_email="applicant@example.com",
                verification_link="/signup/verify/#token=secret",
                expires_at=self.expires_at,
                mail_sender=sender,
            )

        sender.assert_not_called()

    def test_zero_send_count_is_sanitized_failure(self):
        with self.assertRaises(SignupVerificationEmailDeliveryError):
            send_signup_email_verification_email(
                to_email="applicant@example.com",
                verification_link=self.link,
                expires_at=self.expires_at,
                mail_sender=MagicMock(return_value=0),
            )
