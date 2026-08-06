from contextlib import nullcontext
from inspect import getsource
from unittest import TestCase
from unittest.mock import MagicMock

from control.services.signup_account_decision_service import (
    CentralSignupAccountDecisionRepository,
    SignupAccountDecision,
    SignupAccountDecisionRejected,
    decide_signup_account,
)


class SignupAccountDecisionServiceTests(TestCase):
    def setUp(self):
        self.repository = MagicMock()
        self.repository.alias = "central"
        self.repository.apply_request_decision.return_value = "user-reference"
        self.repository.activate_verified_user.return_value = True

    def _decision(self, **overrides):
        values = {
            "signup_request_id": "request-reference",
            "expected_version": 3,
            "actor_user_id": "actor-reference",
            "decision": "approved",
            "reason_code": "review.accepted",
            "note": "review completed",
        }
        values.update(overrides)
        return SignupAccountDecision(**values)

    def test_approval_transitions_activates_and_appends_event(self):
        decide_signup_account(
            self._decision(),
            repository=self.repository,
            atomic_context=nullcontext(),
        )

        self.repository.apply_request_decision.assert_called_once()
        self.repository.activate_verified_user.assert_called_once()
        self.repository.append_decision_event.assert_called_once()

    def test_rejection_never_activates_user(self):
        decide_signup_account(
            self._decision(decision="rejected"),
            repository=self.repository,
            atomic_context=nullcontext(),
        )

        self.repository.activate_verified_user.assert_not_called()
        event = self.repository.append_decision_event.call_args.kwargs
        self.assertEqual(event["decision"], "rejected")

    def test_stale_or_ineligible_request_stops_followup_writes(self):
        self.repository.apply_request_decision.return_value = None

        with self.assertRaises(SignupAccountDecisionRejected):
            decide_signup_account(
                self._decision(),
                repository=self.repository,
                atomic_context=nullcontext(),
            )

        self.repository.activate_verified_user.assert_not_called()
        self.repository.append_decision_event.assert_not_called()

    def test_activation_failure_stops_event_and_rolls_back_context(self):
        self.repository.activate_verified_user.return_value = False
        atomic = MagicMock()
        atomic.__enter__.return_value = atomic
        atomic.__exit__.return_value = False

        with self.assertRaises(SignupAccountDecisionRejected):
            decide_signup_account(
                self._decision(),
                repository=self.repository,
                atomic_context=atomic,
            )

        atomic.__exit__.assert_called_once()
        self.repository.append_decision_event.assert_not_called()

    def test_requires_actor_version_and_controlled_decision(self):
        invalid = (
            self._decision(expected_version=0),
            self._decision(actor_user_id=""),
            self._decision(decision="withdrawn"),
            self._decision(reason_code="contains spaces"),
        )
        for decision in invalid:
            with self.subTest(decision=decision):
                with self.assertRaises(ValueError):
                    decide_signup_account(
                        decision,
                        repository=self.repository,
                        atomic_context=nullcontext(),
                    )

        self.repository.apply_request_decision.assert_not_called()

    def test_repository_sql_enforces_expected_state_version_and_verified_user(self):
        source = getsource(
            CentralSignupAccountDecisionRepository.apply_request_decision
        )
        for contract in (
            "signup_request.status='pending_approval'",
            "signup_request.version=%s",
            "signup_user.email_verified=TRUE",
            "signup_user.is_active=FALSE",
            "version=version + 1",
            "RETURNING signup_request.user_id",
        ):
            self.assertIn(contract, source)

    def test_repository_has_no_membership_or_password_writes(self):
        source = getsource(CentralSignupAccountDecisionRepository)
        for forbidden in (
            "join_requests",
            "user_group_map",
            "employee_profile",
            "password_hash",
        ):
            self.assertNotIn(forbidden, source)
