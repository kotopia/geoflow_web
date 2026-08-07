from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from inspect import getsource
from unittest import TestCase
from unittest.mock import MagicMock

from control.services.signup_verification_outbox_service import (
    CentralSignupVerificationOutboxRepository,
    SignupVerificationDeliveryClaim,
    claim_next_signup_email_verification_delivery,
    validate_outbox_error_code,
)


NOW = datetime(2026, 8, 7, 0, 0, tzinfo=timezone.utc)


class SignupVerificationOutboxServiceTests(TestCase):
    def test_claim_repr_hides_identity_recipient_and_lease(self):
        claim = SignupVerificationDeliveryClaim(
            outbox_id="outbox-secret-id",
            signup_request_id="request-secret-id",
            email="applicant@example.com",
            lease_id="lease-secret-id",
            attempt_count=2,
            claim_expires_at=NOW + timedelta(minutes=5),
        )
        shown = repr(claim)
        for value in (
            claim.outbox_id,
            claim.signup_request_id,
            claim.email,
            claim.lease_id,
        ):
            self.assertNotIn(value, shown)

    def test_enqueue_persists_no_token_or_recipient_payload(self):
        source = getsource(CentralSignupVerificationOutboxRepository.enqueue)

        self.assertIn("signup_verification_delivery_outbox", source)
        for forbidden in (
            "raw_token",
            "token_digest",
            "verification_link",
            "recipient_email",
            "password_hash",
        ):
            self.assertNotIn(forbidden, source)

    def test_claim_cancels_ineligible_pending_or_expired_processing_rows(self):
        source = getsource(
            CentralSignupVerificationOutboxRepository.cancel_ineligible
        )

        self.assertIn("status='cancelled'", source)
        self.assertIn("outbox.status='pending'", source)
        self.assertIn("outbox.claim_expires_at <= %s", source)
        self.assertIn("signup_request.status='pending_email_verification'", source)
        self.assertIn("signup_user.email_verified=FALSE", source)
        self.assertIn("signup_user.is_active=FALSE", source)

    def test_claim_supports_skip_locked_and_expired_lease_recovery(self):
        source = getsource(
            CentralSignupVerificationOutboxRepository.claim_next_due
        )

        self.assertIn("SKIP LOCKED", source)
        self.assertIn("outbox.claim_expires_at <= %s", source)
        self.assertIn("outbox.status='processing'", source)
        self.assertIn("attempt_count=outbox.attempt_count + 1", source)

    def test_finalize_retry_and_cancel_are_lease_bound(self):
        methods = (
            CentralSignupVerificationOutboxRepository.mark_delivered,
            CentralSignupVerificationOutboxRepository.release_for_retry,
            CentralSignupVerificationOutboxRepository.mark_cancelled,
        )
        for method in methods:
            with self.subTest(method=method.__name__):
                source = getsource(method)
                self.assertIn("status='processing'", source)
                self.assertIn("lease_id=%s", source)

    def test_error_code_is_strictly_controlled(self):
        self.assertEqual(
            validate_outbox_error_code("MAIL.delivery_failed"),
            "mail.delivery_failed",
        )
        for invalid in (
            "",
            "contains space",
            "recipient@example.com",
            "x" * 65,
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    validate_outbox_error_code(invalid)

    def test_claim_service_rejects_non_positive_lease_before_database(self):
        repository = MagicMock()
        for value in (timedelta(0), timedelta(seconds=-1)):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    claim_next_signup_email_verification_delivery(
                        lease_for=value,
                        repository=repository,
                        atomic_context=nullcontext(),
                    )
        repository.cancel_ineligible.assert_not_called()
        repository.claim_next_due.assert_not_called()


class SignupVerificationOutboxClaimOrchestrationTests(TestCase):
    def test_claim_sweeps_ineligible_rows_before_selecting_due_work(self):
        repository = MagicMock()
        repository.alias = "central"
        repository.claim_next_due.return_value = None

        claim_next_signup_email_verification_delivery(
            lease_for=timedelta(minutes=2),
            repository=repository,
            alias="central",
            atomic_context=nullcontext(),
            clock=lambda: NOW,
        )

        method_names = [call[0] for call in repository.method_calls]
        self.assertEqual(
            method_names[:2],
            ["cancel_ineligible", "claim_next_due"],
        )
