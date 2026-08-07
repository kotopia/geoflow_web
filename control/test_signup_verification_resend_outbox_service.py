from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from inspect import getsource
from unittest import TestCase
from unittest.mock import MagicMock

from control.services.signup_verification_resend_outbox_service import (
    CentralSignupVerificationResendOutboxRepository,
    SignupVerificationResendOutboxTarget,
    queue_signup_email_verification_resend,
)


NOW = datetime(2026, 8, 7, 0, 0, tzinfo=timezone.utc)


class SignupVerificationResendOutboxServiceTests(TestCase):
    def setUp(self):
        self.resend_repository = MagicMock()
        self.resend_repository.alias = "central"
        self.resend_repository.lock_eligible_target.return_value = (
            SignupVerificationResendOutboxTarget(
                signup_request_id="request-reference"
            )
        )
        self.outbox_repository = MagicMock()
        self.outbox_repository.alias = "central"
        self.outbox_repository.enqueue.return_value = True

    def test_resend_queues_intent_without_token_or_key_material(self):
        queued = queue_signup_email_verification_resend(
            " Applicant@Example.com ",
            cooldown=timedelta(minutes=10),
            alias="central",
            resend_repository=self.resend_repository,
            outbox_repository=self.outbox_repository,
            atomic_context=nullcontext(),
            clock=lambda: NOW,
        )

        self.assertTrue(queued)
        target_call = self.resend_repository.lock_eligible_target.call_args.kwargs
        self.assertEqual(target_call["email"], "applicant@example.com")
        self.outbox_repository.enqueue.assert_called_once()
        persisted = repr(self.outbox_repository.enqueue.call_args)
        self.assertNotIn("applicant@example.com", persisted)
        self.assertNotIn("token", persisted)
        self.assertNotIn("key_ring", persisted)

    def test_ineligible_or_cooldown_target_has_no_outbox_write(self):
        self.resend_repository.lock_eligible_target.return_value = None

        queued = queue_signup_email_verification_resend(
            "applicant@example.com",
            cooldown=timedelta(minutes=10),
            alias="central",
            resend_repository=self.resend_repository,
            outbox_repository=self.outbox_repository,
            atomic_context=nullcontext(),
            clock=lambda: NOW,
        )

        self.assertFalse(queued)
        self.outbox_repository.enqueue.assert_not_called()

    def test_cooldown_uses_last_outbox_update_not_original_enqueue_time(self):
        source = getsource(
            CentralSignupVerificationResendOutboxRepository.lock_eligible_target
        )

        self.assertIn("updated_at > %s", source)
        self.assertNotIn("created_at > %s", source)
        self.assertIn("status IN ('pending', 'processing')", source)
