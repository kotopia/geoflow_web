from contextlib import nullcontext
from inspect import getsource
from unittest.mock import MagicMock

from django.test import SimpleTestCase

from control.services.signup_verification_service import (
    PUBLIC_VERIFICATION_ERROR,
    CentralSignupVerificationRepository,
    EmailVerificationConfigurationError,
    EmailVerificationGrant,
    EmailVerificationRejected,
    verify_signup_email,
)


class SignupEmailVerificationServiceTests(SimpleTestCase):
    def setUp(self):
        self.token_verifier = MagicMock()
        self.token_verifier.consume.return_value = EmailVerificationGrant(
            user_id="user-reference",
            signup_request_id="request-reference",
        )
        self.repository = MagicMock()
        self.repository.transition_request_to_pending_approval.return_value = True
        self.repository.mark_email_verified.return_value = True

    def test_grant_repr_does_not_expose_central_identifiers(self):
        grant = self.token_verifier.consume.return_value

        self.assertNotIn(grant.user_id, repr(grant))
        self.assertNotIn(grant.signup_request_id, repr(grant))

    def _verify(self):
        verify_signup_email(
            "opaque-test-token",
            token_verifier=self.token_verifier,
            repository=self.repository,
            atomic_context=nullcontext(),
        )

    def test_success_marks_verified_transitions_request_and_appends_event(self):
        self._verify()

        self.repository.transition_request_to_pending_approval.assert_called_once()
        self.repository.mark_email_verified.assert_called_once()
        self.repository.append_verified_event.assert_called_once()

        transition = self.repository.transition_request_to_pending_approval.call_args.kwargs
        verified = self.repository.mark_email_verified.call_args.kwargs
        event = self.repository.append_verified_event.call_args.kwargs
        self.assertEqual(transition["user_id"], "user-reference")
        self.assertEqual(transition["signup_request_id"], "request-reference")
        self.assertEqual(verified["user_id"], "user-reference")
        self.assertEqual(event["signup_request_id"], "request-reference")

    def test_success_contract_has_no_activation_password_or_membership_writes(self):
        self._verify()
        called_methods = {call[0] for call in self.repository.method_calls}
        self.assertEqual(
            called_methods,
            {
                "transition_request_to_pending_approval",
                "mark_email_verified",
                "append_verified_event",
            },
        )
        for call in self.repository.method_calls:
            payload = call.kwargs
            self.assertNotIn("is_active", payload)
            self.assertNotIn("password", payload)
            self.assertNotIn("password_hash", payload)
            self.assertNotIn("token", payload)

    def test_invalid_expired_or_replayed_token_fails_without_writes(self):
        for failure_case in ("invalid", "expired", "replayed"):
            with self.subTest(failure_case=failure_case):
                self.repository.reset_mock()
                self.token_verifier.consume.return_value = None
                with self.assertRaisesMessage(
                    EmailVerificationRejected, PUBLIC_VERIFICATION_ERROR
                ):
                    self._verify()
                self.repository.transition_request_to_pending_approval.assert_not_called()
                self.repository.mark_email_verified.assert_not_called()
                self.repository.append_verified_event.assert_not_called()

    def test_wrong_request_status_rolls_back_and_stops_followup_writes(self):
        self.repository.transition_request_to_pending_approval.return_value = False
        atomic = MagicMock()
        atomic.__enter__.return_value = atomic
        atomic.__exit__.return_value = False

        with self.assertRaisesMessage(EmailVerificationRejected, PUBLIC_VERIFICATION_ERROR):
            verify_signup_email(
                "opaque-test-token",
                token_verifier=self.token_verifier,
                repository=self.repository,
                atomic_context=atomic,
            )

        atomic.__enter__.assert_called_once()
        atomic.__exit__.assert_called_once()
        self.repository.mark_email_verified.assert_not_called()
        self.repository.append_verified_event.assert_not_called()

    def test_user_update_failure_rolls_back_request_transition_and_event(self):
        self.repository.mark_email_verified.return_value = False
        atomic = MagicMock()
        atomic.__enter__.return_value = atomic
        atomic.__exit__.return_value = False

        with self.assertRaisesMessage(EmailVerificationRejected, PUBLIC_VERIFICATION_ERROR):
            verify_signup_email(
                "opaque-test-token",
                token_verifier=self.token_verifier,
                repository=self.repository,
                atomic_context=atomic,
            )

        atomic.__exit__.assert_called_once()
        self.repository.append_verified_event.assert_not_called()

    def test_raw_token_is_only_passed_to_verifier(self):
        self._verify()
        self.token_verifier.consume.assert_called_once_with("opaque-test-token")
        for call in self.repository.method_calls:
            self.assertNotIn("opaque-test-token", repr(call))

    def test_central_user_write_preserves_inactive_state_and_password_hash(self):
        source = getsource(CentralSignupVerificationRepository.mark_email_verified)
        normalized = " ".join(source.split()).lower()
        self.assertIn("set email_verified=true", normalized)
        self.assertIn("is_active=false", normalized)
        self.assertNotIn("set is_active", normalized)
        self.assertNotIn("password_hash", normalized)

    def test_database_alias_mismatch_fails_before_token_or_state_writes(self):
        class AliasBoundVerifier:
            alias = "tenant"

            def __init__(self):
                self.consume = MagicMock()

        verifier = AliasBoundVerifier()
        repository = MagicMock()
        repository.alias = "central"

        with self.assertRaises(EmailVerificationConfigurationError):
            verify_signup_email(
                "opaque-test-token",
                token_verifier=verifier,
                repository=repository,
                atomic_context=nullcontext(),
            )

        verifier.consume.assert_not_called()
        repository.transition_request_to_pending_approval.assert_not_called()
        repository.mark_email_verified.assert_not_called()
        repository.append_verified_event.assert_not_called()

    def test_verified_event_does_not_require_database_uuid_extension(self):
        source = getsource(
            CentralSignupVerificationRepository.append_verified_event
        )

        self.assertIn("uuid.uuid4()", source)
        self.assertNotIn("gen_random_uuid()", source)
