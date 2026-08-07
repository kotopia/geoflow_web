from contextlib import nullcontext
from datetime import datetime, timezone
from unittest import TestCase
from inspect import getsource
from unittest.mock import MagicMock, patch

from control.services.signup_service import (
    SignupRequestInput,
    SignupRequestReceipt,
    SignupRequestRejected,
)
from control.services.signup_verification_service import (
    EmailVerificationConfigurationError,
)
from control.services.signup_verification_signup_outbox_service import (
    create_signup_request_with_verification_outbox,
)


NOW = datetime(2026, 8, 7, 0, 0, tzinfo=timezone.utc)


class SignupVerificationSignupOutboxServiceTests(TestCase):
    def setUp(self):
        self.signup_repository = MagicMock()
        self.signup_repository.alias = "central"
        self.outbox_repository = MagicMock()
        self.outbox_repository.alias = "central"
        self.outbox_repository.enqueue.return_value = True
        self.data = SignupRequestInput(
            email="applicant@example.com",
            password="secret-password-value",
            name_display="Applicant",
            contact_phone="",
            organization_name="Org",
            signup_purpose="Work",
            terms_agreed=True,
            privacy_agreed=True,
        )

    @patch(
        "control.services.signup_verification_signup_outbox_service."
        "create_signup_request",
        return_value=SignupRequestReceipt(
            user_id="user-reference",
            signup_request_id="request-reference",
        ),
    )
    def test_signup_and_outbox_intent_share_one_outer_transaction(
        self,
        create_signup,
    ):
        queued = create_signup_request_with_verification_outbox(
            self.data,
            alias="central",
            signup_repository=self.signup_repository,
            outbox_repository=self.outbox_repository,
            atomic_context=nullcontext(),
            clock=lambda: NOW,
        )

        self.assertNotIn("request-reference", repr(queued))
        create_signup.assert_called_once()
        self.outbox_repository.enqueue.assert_called_once_with(
            signup_request_id="request-reference",
            available_at=NOW,
            created_at=NOW,
        )
        payload = repr(self.outbox_repository.enqueue.call_args)
        self.assertNotIn(self.data.password, payload)
        self.assertNotIn("token", payload)

    @patch(
        "control.services.signup_verification_signup_outbox_service."
        "create_signup_request",
        return_value=SignupRequestReceipt(
            user_id="user-reference",
            signup_request_id="request-reference",
        ),
    )
    def test_outbox_enqueue_failure_rejects_signup_for_transaction_rollback(
        self,
        _create_signup,
    ):
        self.outbox_repository.enqueue.return_value = False

        with self.assertRaises(SignupRequestRejected):
            create_signup_request_with_verification_outbox(
                self.data,
                alias="central",
                signup_repository=self.signup_repository,
                outbox_repository=self.outbox_repository,
                atomic_context=nullcontext(),
                clock=lambda: NOW,
            )

    def test_cross_database_alias_mismatch_fails_before_any_write(self):
        self.outbox_repository.alias = "tenant"

        with self.assertRaises(EmailVerificationConfigurationError):
            create_signup_request_with_verification_outbox(
                self.data,
                alias="central",
                signup_repository=self.signup_repository,
                outbox_repository=self.outbox_repository,
                atomic_context=nullcontext(),
                clock=lambda: NOW,
            )

        self.signup_repository.create_inactive_user.assert_not_called()
        self.outbox_repository.enqueue.assert_not_called()

    def test_orchestrator_marks_password_bearing_input_as_sensitive(self):
        source = getsource(create_signup_request_with_verification_outbox)

        self.assertIn('@sensitive_variables("data", "receipt")', source)
