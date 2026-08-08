from datetime import datetime, timezone as datetime_timezone
from inspect import getsource
from unittest.mock import MagicMock

from django.test import SimpleTestCase

from control.services.signup_retention_service import (
    CentralSignupRetentionRepository,
    SignupRetentionCandidate,
    SignupRetentionResult,
    one_year_before,
    purge_terminal_signup_data,
)


UTC = datetime_timezone.utc


class SignupRetentionServiceTests(SimpleTestCase):
    def test_one_year_before_uses_calendar_anniversary(self):
        self.assertEqual(
            one_year_before(datetime(2026, 8, 8, 9, 0, tzinfo=UTC)),
            datetime(2025, 8, 8, 9, 0, tzinfo=UTC),
        )

    def test_one_year_before_handles_leap_day(self):
        self.assertEqual(
            one_year_before(datetime(2024, 2, 29, 12, 0, tzinfo=UTC)),
            datetime(2023, 2, 28, 12, 0, tzinfo=UTC),
        )

    def test_dry_run_never_purges_candidates(self):
        repository = MagicMock()
        repository.list_candidates.return_value = (
            SignupRetentionCandidate(
                signup_request_id="request-id",
                user_id="user-id",
                status="rejected",
                retention_started_at=datetime(2025, 8, 1, tzinfo=UTC),
            ),
        )

        result = purge_terminal_signup_data(
            repository=repository,
            execute=False,
            clock=lambda: datetime(2026, 8, 8, tzinfo=UTC),
        )

        self.assertEqual(
            result,
            SignupRetentionResult(candidates=1, purged=0, dry_run=True),
        )
        repository.purge_candidate.assert_not_called()
        cutoff = repository.list_candidates.call_args.kwargs["cutoff"]
        self.assertEqual(cutoff, datetime(2025, 8, 8, tzinfo=UTC))

    def test_execute_purges_only_returned_candidates(self):
        repository = MagicMock()
        repository.alias = "default"
        candidate = SignupRetentionCandidate(
            signup_request_id="request-id",
            user_id="user-id",
            status="expired",
            retention_started_at=datetime(2025, 8, 1, tzinfo=UTC),
        )
        repository.list_candidates.return_value = (candidate,)

        from contextlib import nullcontext
        from unittest.mock import patch

        with patch(
            "control.services.signup_retention_service.transaction.atomic",
            return_value=nullcontext(),
        ):
            result = purge_terminal_signup_data(
                repository=repository,
                execute=True,
                clock=lambda: datetime(2026, 8, 8, tzinfo=UTC),
            )

        self.assertEqual(
            result,
            SignupRetentionResult(candidates=1, purged=1, dry_run=False),
        )
        repository.purge_candidate.assert_called_once_with(candidate)

    def test_batch_size_is_bounded(self):
        with self.assertRaises(ValueError):
            purge_terminal_signup_data(batch_size=0)
        with self.assertRaises(ValueError):
            purge_terminal_signup_data(batch_size=501)


class SignupRetentionRepositorySqlContractTests(SimpleTestCase):
    def test_candidate_query_is_terminal_inactive_and_excludes_authoritative_links(self):
        source = getsource(CentralSignupRetentionRepository.list_candidates)
        dynamic_source = getsource(CentralSignupRetentionRepository._dynamic_safety_clauses)
        for required in (
            "status IN ('rejected', 'expired')",
            "signup_user.is_active=FALSE",
            "user_group_map",
            "join_requests",
            "decided_by_user_id",
            "actor_user_id",
            "LIMIT %s",
        ):
            self.assertIn(required, source)
        self.assertIn("decided_by", dynamic_source)
        self.assertIn("owner_user_id", dynamic_source)

    def test_join_request_email_schema_compatibility_is_explicit(self):
        source = getsource(CentralSignupRetentionRepository._join_request_email_columns)
        self.assertIn('"email"', source)
        self.assertIn('"requested_email"', source)

    def test_purge_dependency_order_and_final_safety_rechecks(self):
        source = getsource(CentralSignupRetentionRepository.purge_candidate)
        outbox = source.index("DELETE FROM signup_verification_delivery_outbox")
        token = source.index("DELETE FROM signup_email_verification_tokens")
        event = source.index("DELETE FROM signup_request_events")
        request = source.index("DELETE FROM signup_requests")
        user = source.index("DELETE FROM users AS signup_user")
        self.assertLess(outbox, request)
        self.assertLess(token, request)
        self.assertLess(event, request)
        self.assertLess(request, user)
        for required in (
            "signup_user.is_active=FALSE",
            "NOT EXISTS",
            "user_group_map",
            "join_requests",
            "FOR UPDATE OF signup_request, signup_user",
        ):
            self.assertIn(required, source)


class SignupRetentionJoinSchemaCompatibilityTests(SimpleTestCase):
    def test_join_request_safety_supports_both_schema_generations(self):
        email_source = getsource(
            CentralSignupRetentionRepository._join_request_email_columns
        )
        decider_source = getsource(
            CentralSignupRetentionRepository._join_request_decider_columns
        )
        dynamic_source = getsource(
            CentralSignupRetentionRepository._dynamic_safety_clauses
        )
        self.assertIn('("requested_email", "email")', email_source)
        self.assertIn('("decided_by_user_id", "decided_by")', decider_source)
        self.assertIn('for column in self._join_request_email_columns', dynamic_source)
        self.assertIn('for column in self._join_request_decider_columns', dynamic_source)

    def test_calendar_year_retention_not_fixed_365_days(self):
        source = getsource(one_year_before)
        self.assertIn('replace(year=moment.year - 1)', source)
        self.assertNotIn('timedelta(days=365)', source)


class SignupRetentionDjangoBridgeTests(SimpleTestCase):
    def test_retention_cleans_unexpected_django_session_bridge_identity(self):
        source = getsource(
            CentralSignupRetentionRepository._anonymize_django_session_bridge
        )
        self.assertIn("auth_user", source)
        self.assertIn("erased-session-", source)
        self.assertIn("make_password(None)", source)
        self.assertIn("is_active=FALSE", source)
        self.assertIn("last_login=NULL", source)

    def test_bridge_cleanup_precedes_final_central_user_delete(self):
        source = getsource(CentralSignupRetentionRepository.purge_candidate)
        self.assertLess(
            source.index("_anonymize_django_session_bridge"),
            source.index("DELETE FROM users AS signup_user"),
        )


class SignupRetentionLegacyTokenCleanupTests(SimpleTestCase):
    def test_retention_cleans_both_legacy_password_token_generations(self):
        source = getsource(
            CentralSignupRetentionRepository._delete_legacy_password_tokens
        )
        self.assertIn('"password_reset_tokens", "user_tokens"', source)
        self.assertIn("_table_exists", source)
        self.assertIn("DELETE FROM {table} WHERE user_id=%s", source)
