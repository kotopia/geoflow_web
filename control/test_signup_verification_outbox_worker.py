from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from unittest import TestCase
from unittest.mock import MagicMock

from control.services.signup_verification_email_delivery import (
    SignupVerificationEmailDeliveryError,
)
from control.services.signup_verification_outbox_service import (
    SignupVerificationDeliveryClaim,
    SignupVerificationLockedDeliveryTarget,
)
from control.services.signup_verification_outbox_worker import (
    process_signup_verification_delivery_claim,
)
from control.services.signup_verification_token_service import (
    HmacSha256VerificationKeyRing,
)


NOW = datetime(2026, 8, 7, 0, 0, tzinfo=timezone.utc)


class SignupVerificationOutboxWorkerTests(TestCase):
    def setUp(self):
        self.outbox = MagicMock()
        self.outbox.alias = "central"
        self.outbox.lock_current_claim.return_value = (
            SignupVerificationLockedDeliveryTarget(
                signup_request_id="request-reference",
                email="current@example.com",
            )
        )
        self.outbox.mark_delivered.return_value = True
        self.outbox.release_for_retry.return_value = True
        self.outbox.mark_cancelled.return_value = True
        self.token_repository = MagicMock()
        self.token_repository.alias = "central"
        self.token_repository.create_digest.return_value = True
        self.key_ring = HmacSha256VerificationKeyRing(
            active_key_id="current",
            keys={"current": b"k" * 32},
        )
        self.claim = SignupVerificationDeliveryClaim(
            outbox_id="outbox-reference",
            signup_request_id="request-reference",
            email="applicant@example.com",
            lease_id="lease-reference",
            attempt_count=1,
            claim_expires_at=NOW + timedelta(minutes=10),
        )

    def _process(self, **overrides):
        values = {
            "claim": self.claim,
            "verification_url": "https://example.invalid/signup/verify/",
            "ttl": timedelta(hours=1),
            "retry_at": NOW + timedelta(minutes=10),
            "key_ring": self.key_ring,
            "alias": "central",
            "outbox_repository": self.outbox,
            "token_repository": self.token_repository,
            "atomic_context": nullcontext(),
            "clock": lambda: NOW,
            "token_factory": lambda _size: "s" * 43,
            "deliver": MagicMock(),
        }
        values.update(overrides)
        return process_signup_verification_delivery_claim(**values)

    def test_success_replaces_token_delivers_after_transaction_and_finalizes(self):
        deliver = MagicMock()
        result = self._process(deliver=deliver)

        self.assertEqual(result.status, "delivered")
        self.outbox.lock_current_claim.assert_called_once()
        self.token_repository.revoke_unconsumed.assert_called_once()
        self.token_repository.create_digest.assert_called_once()
        deliver.assert_called_once()
        self.assertEqual(
            deliver.call_args.kwargs["to_email"],
            "current@example.com",
        )
        self.assertNotEqual(
            deliver.call_args.kwargs["to_email"],
            self.claim.email,
        )
        self.outbox.mark_delivered.assert_called_once()
        self.outbox.release_for_retry.assert_not_called()

    def test_stale_claim_never_issues_or_delivers(self):
        self.outbox.lock_current_claim.return_value = None
        deliver = MagicMock()

        result = self._process(deliver=deliver)

        self.assertEqual(result.status, "stale")
        self.token_repository.revoke_unconsumed.assert_not_called()
        self.token_repository.create_digest.assert_not_called()
        deliver.assert_not_called()

    def test_lease_expiry_after_token_commit_prevents_delivery(self):
        times = iter(
            (
                NOW,
                self.claim.claim_expires_at,
            )
        )
        deliver = MagicMock()

        result = self._process(
            clock=lambda: next(times),
            deliver=deliver,
        )

        self.assertEqual(result.status, "stale_before_delivery")
        self.token_repository.create_digest.assert_called_once()
        deliver.assert_not_called()
        self.outbox.mark_delivered.assert_not_called()


    def test_insufficient_lease_budget_for_email_timeout_prevents_delivery(self):
        claim = SignupVerificationDeliveryClaim(
            outbox_id="outbox-reference",
            signup_request_id="request-reference",
            email="applicant@example.com",
            lease_id="lease-reference",
            attempt_count=1,
            claim_expires_at=NOW + timedelta(seconds=30),
        )
        deliver = MagicMock()

        result = process_signup_verification_delivery_claim(
            claim,
            verification_url="https://example.invalid/signup/verify/",
            ttl=timedelta(hours=1),
            retry_at=NOW + timedelta(minutes=10),
            key_ring=self.key_ring,
            alias="central",
            outbox_repository=self.outbox,
            token_repository=self.token_repository,
            atomic_context=nullcontext(),
            clock=lambda: NOW,
            token_factory=lambda _size: "s" * 43,
            deliver=deliver,
            email_timeout_seconds=30,
        )

        self.assertEqual(result.status, "stale_before_delivery")
        deliver.assert_not_called()

    def test_delivery_failure_requeues_without_exposing_token(self):
        deliver = MagicMock(side_effect=SignupVerificationEmailDeliveryError())

        result = self._process(deliver=deliver)

        self.assertEqual(result.status, "retry_scheduled")
        retry = self.outbox.release_for_retry.call_args.kwargs
        self.assertEqual(retry["error_code"], "mail.delivery_failed")
        self.assertNotIn("applicant@example.com", repr(retry))
        self.assertNotIn("v1.current.", repr(retry))

    def test_claim_above_max_attempts_cancels_before_token_or_delivery(self):
        self.claim = SignupVerificationDeliveryClaim(
            outbox_id="outbox-reference",
            signup_request_id="request-reference",
            email="applicant@example.com",
            lease_id="lease-reference",
            attempt_count=4,
            claim_expires_at=NOW + timedelta(minutes=10),
        )
        deliver = MagicMock()

        result = self._process(
            deliver=deliver,
            max_attempts=3,
        )

        self.assertEqual(result.status, "max_attempts_exhausted")
        self.outbox.mark_cancelled.assert_called_once()
        self.outbox.lock_current_claim.assert_not_called()
        self.token_repository.revoke_unconsumed.assert_not_called()
        self.token_repository.create_digest.assert_not_called()
        deliver.assert_not_called()

    def test_delivery_failure_at_max_attempts_cancels_without_retry(self):
        self.claim = SignupVerificationDeliveryClaim(
            outbox_id="outbox-reference",
            signup_request_id="request-reference",
            email="applicant@example.com",
            lease_id="lease-reference",
            attempt_count=3,
            claim_expires_at=NOW + timedelta(minutes=10),
        )
        deliver = MagicMock(side_effect=SignupVerificationEmailDeliveryError())

        result = self._process(
            deliver=deliver,
            max_attempts=3,
        )

        self.assertEqual(result.status, "max_attempts_exhausted")
        cancel = self.outbox.mark_cancelled.call_args.kwargs
        self.assertEqual(
            cancel["error_code"],
            "mail.max_attempts_exceeded",
        )
        self.outbox.release_for_retry.assert_not_called()

    def test_invalid_max_attempts_fails_before_database_work(self):
        for value in (0, -1, True, "3"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self._process(max_attempts=value)
        self.outbox.lock_current_claim.assert_not_called()

    def test_retry_finalization_reports_stale_lease(self):
        self.outbox.release_for_retry.return_value = False
        deliver = MagicMock(side_effect=SignupVerificationEmailDeliveryError())

        result = self._process(deliver=deliver)

        self.assertEqual(result.status, "stale_after_failure")

    def test_delivery_finalization_reports_stale_lease(self):
        self.outbox.mark_delivered.return_value = False

        result = self._process()

        self.assertEqual(result.status, "stale_after_delivery")

    def test_retry_attempt_revokes_previous_unconsumed_token_again(self):
        self.claim = SignupVerificationDeliveryClaim(
            outbox_id="outbox-reference",
            signup_request_id="request-reference",
            email="applicant@example.com",
            lease_id="second-lease",
            attempt_count=2,
            claim_expires_at=NOW + timedelta(minutes=10),
        )

        self._process()

        self.token_repository.revoke_unconsumed.assert_called_once()
        self.token_repository.create_digest.assert_called_once()
