from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from inspect import getsource
from unittest import TestCase
from unittest.mock import MagicMock

from control.services.signup_request_expiration_service import (
    CentralSignupRequestExpirationRepository,
    expire_signup_requests,
)


class SignupRequestExpirationServiceTests(TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)
        self.cutoff = self.now - timedelta(days=1)
        self.repository = MagicMock()
        self.repository.alias = "central"
        self.repository.expire_batch.return_value = (
            "request-one",
            "request-two",
        )

    def _expire(self, **overrides):
        values = {
            "status": "pending_email_verification",
            "cutoff": self.cutoff,
            "batch_size": 100,
            "repository": self.repository,
            "atomic_context": nullcontext(),
            "clock": lambda: self.now,
        }
        values.update(overrides)
        return expire_signup_requests(**values)

    def test_email_verification_expiration_updates_and_appends_events_atomically(self):
        count = self._expire()

        self.assertEqual(count, 2)
        self.repository.expire_batch.assert_called_once_with(
            status="pending_email_verification",
            cutoff=self.cutoff,
            expired_at=self.now,
            reason_code="email_verification_timeout",
            batch_size=100,
        )
        self.repository.append_expired_events.assert_called_once_with(
            signup_request_ids=("request-one", "request-two"),
            from_status="pending_email_verification",
            reason_code="email_verification_timeout",
            created_at=self.now,
        )

    def test_approval_expiration_uses_separate_controlled_reason(self):
        self._expire(status="pending_approval")

        self.assertEqual(
            self.repository.expire_batch.call_args.kwargs["reason_code"],
            "approval_timeout",
        )
        self.assertEqual(
            self.repository.append_expired_events.call_args.kwargs[
                "from_status"
            ],
            "pending_approval",
        )

    def test_empty_batch_is_a_successful_noop(self):
        self.repository.expire_batch.return_value = ()

        self.assertEqual(self._expire(), 0)

        self.repository.append_expired_events.assert_called_once_with(
            signup_request_ids=(),
            from_status="pending_email_verification",
            reason_code="email_verification_timeout",
            created_at=self.now,
        )

    def test_invalid_status_future_cutoff_and_batch_size_fail_before_write(self):
        invalid = (
            {"status": "approved"},
            {"cutoff": self.now + timedelta(seconds=1)},
            {"batch_size": 0},
            {"batch_size": 501},
        )
        for values in invalid:
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    self._expire(**values)

        self.repository.expire_batch.assert_not_called()
        self.repository.append_expired_events.assert_not_called()

    def test_repository_sql_is_bounded_locked_and_keeps_user_inactive(self):
        source = getsource(
            CentralSignupRequestExpirationRepository.expire_batch
        )
        for contract in (
            "FOR UPDATE OF signup_request SKIP LOCKED",
            "LIMIT %s",
            "signup_user.is_active=FALSE",
            "SET status='expired'",
            "decided_by_user_id=NULL",
            "version=version + 1",
            "RETURNING signup_request.id",
        ):
            self.assertIn(contract, source)
        for forbidden in (
            "SET is_active",
            "password_hash",
            "join_requests",
            "user_group_map",
            "employee_profile",
        ):
            self.assertNotIn(forbidden, source)

    def test_event_insert_is_append_only_and_uses_python_uuid(self):
        source = getsource(
            CentralSignupRequestExpirationRepository.append_expired_events
        )
        for contract in (
            "uuid.uuid4()",
            "INSERT INTO signup_request_events",
            "'expired'",
            "actor_user_id",
            "NULL",
        ):
            self.assertIn(contract, source)
        self.assertNotIn("UPDATE signup_request_events", source)
        self.assertNotIn("DELETE FROM signup_request_events", source)
