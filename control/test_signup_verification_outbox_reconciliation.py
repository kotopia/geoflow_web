from contextlib import nullcontext
from datetime import datetime, timezone
from inspect import getsource
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock

from control.services.signup_verification_outbox_reconciliation import (
    CentralSignupVerificationOutboxReconciliationRepository,
    SignupVerificationOutboxReconciliationSummary,
    queue_missing_signup_verification_outbox_batch,
    summarize_signup_verification_outbox,
)


NOW = datetime(2026, 8, 7, 2, 0, tzinfo=timezone.utc)
CUTOFF = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)
CONTROL_DIR = Path(__file__).resolve().parent


class SignupVerificationOutboxReconciliationTests(TestCase):
    def test_summary_returns_counts_only(self):
        repository = MagicMock()
        repository.alias = "central"
        repository.summarize.return_value = (
            SignupVerificationOutboxReconciliationSummary(2, 1, 3, 0)
        )

        summary = summarize_signup_verification_outbox(
            repository=repository,
            alias="central",
            clock=lambda: NOW,
        )

        self.assertEqual(summary.eligible_missing_outbox, 2)
        self.assertEqual(summary.active_outbox_ineligible, 1)
        self.assertEqual(summary.expired_processing_leases, 3)
        self.assertEqual(summary.duplicate_live_tokens, 0)
        self.assertNotIn("email", repr(summary).lower())
        self.assertNotIn("token=", repr(summary).lower())

    def test_backfill_is_bounded_and_enqueues_only_locked_request_ids(self):
        repository = MagicMock()
        repository.alias = "central"
        repository.lock_missing_targets.return_value = ["request-a", "request-b"]
        outbox_repository = MagicMock()
        outbox_repository.alias = "central"
        outbox_repository.enqueue.side_effect = [True, True]

        result = queue_missing_signup_verification_outbox_batch(
            submitted_after=CUTOFF,
            limit=2,
            repository=repository,
            outbox_repository=outbox_repository,
            alias="central",
            atomic_context=nullcontext(),
            clock=lambda: NOW,
        )

        self.assertEqual(result.selected, 2)
        self.assertEqual(result.enqueued, 2)
        repository.lock_missing_targets.assert_called_once_with(
            submitted_after=CUTOFF,
            limit=2,
        )
        self.assertEqual(outbox_repository.enqueue.call_count, 2)
        for call in outbox_repository.enqueue.call_args_list:
            self.assertNotIn("email", repr(call).lower())
            self.assertNotIn("token", repr(call).lower())

    def test_backfill_requires_explicit_aware_cutoff_and_positive_limit(self):
        repository = MagicMock()
        outbox_repository = MagicMock()
        invalid = (
            (datetime(2026, 8, 1), 1),
            (CUTOFF, 0),
            (CUTOFF, -1),
            (CUTOFF, True),
        )
        for submitted_after, limit in invalid:
            with self.subTest(submitted_after=submitted_after, limit=limit):
                with self.assertRaises(ValueError):
                    queue_missing_signup_verification_outbox_batch(
                        submitted_after=submitted_after,
                        limit=limit,
                        repository=repository,
                        outbox_repository=outbox_repository,
                    )
        repository.lock_missing_targets.assert_not_called()
        outbox_repository.enqueue.assert_not_called()

    def test_repository_backfill_query_is_lock_bounded_and_pii_free(self):
        source = getsource(
            CentralSignupVerificationOutboxReconciliationRepository.lock_missing_targets
        )
        for required in (
            "signup_request.status='pending_email_verification'",
            "signup_request.submitted_at >= %s",
            "signup_user.email_verified=FALSE",
            "signup_user.is_active=FALSE",
            "FOR UPDATE OF signup_request SKIP LOCKED",
            "LIMIT %s",
        ):
            self.assertIn(required, source)
        self.assertNotIn("signup_user.email,", source)
        self.assertNotIn("password_hash", source)
        self.assertNotIn("outbox.status IN", source)
        self.assertIn("NOT EXISTS", source)

    def test_backfill_query_does_not_restart_delivered_or_cancelled_history(self):
        source = getsource(
            CentralSignupVerificationOutboxReconciliationRepository.lock_missing_targets
        )

        self.assertIn("NOT EXISTS", source)
        self.assertIn("outbox.delivery_type='signup_email_verification'", source)
        self.assertNotIn("outbox.status IN", source)

    def test_management_backfill_command_requires_execute_cutoff_and_limit(self):
        command = (
            CONTROL_DIR
            / "management/commands/queue_signup_verification_outbox_backfill.py"
        ).read_text(encoding="utf-8")

        self.assertIn('parser.add_argument("--limit"', command)
        self.assertIn('parser.add_argument("--submitted-after"', command)
        self.assertIn('parser.add_argument("--execute"', command)
        self.assertIn('if not options["execute"]', command)
        self.assertNotIn("send_mail", command)
        self.assertNotIn("issue_signup_email_verification_token", command)

    def test_diagnostic_command_outputs_counts_not_identifiers(self):
        command = (
            CONTROL_DIR
            / "management/commands/check_signup_verification_outbox.py"
        ).read_text(encoding="utf-8")

        for required in (
            "eligible_missing_outbox=",
            "active_outbox_ineligible=",
            "expired_processing_leases=",
            "duplicate_live_tokens=",
        ):
            self.assertIn(required, command)
        for forbidden in ("email", "signup_request_id", "token_digest", "raw_token"):
            self.assertNotIn(forbidden, command)
