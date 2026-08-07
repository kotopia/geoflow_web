from contextlib import nullcontext
from datetime import timedelta
from unittest.mock import MagicMock

from django.test import SimpleTestCase

from control.services.signup_email_verification_signup_service import (
    create_signup_request_with_verification_token,
)
from control.services.signup_service import SignupRequestInput
from control.services.signup_verification_service import (
    EmailVerificationConfigurationError,
)
from control.services.signup_verification_token_service import (
    HmacSha256VerificationKeyRing,
    SignupEmailVerificationTokenIssuanceRejected,
)


class SignupEmailVerificationOrchestrationTests(SimpleTestCase):
    def setUp(self):
        self.data = SignupRequestInput(
            email="applicant@example.com",
            password="not-asserted-raw",
            name_display="신청자",
            contact_phone="",
            organization_name="기관",
            signup_purpose="업무 활용",
            terms_agreed=True,
            privacy_agreed=True,
        )
        self.key_ring = HmacSha256VerificationKeyRing(
            active_key_id="current",
            keys={"current": b"k" * 32},
        )
        self.signup_repository = MagicMock()
        self.signup_repository.alias = "central"
        self.signup_repository.account_exists.return_value = False
        self.signup_repository.create_inactive_user.return_value = "user-reference"
        self.signup_repository.create_signup_request.return_value = "request-reference"
        self.token_repository = MagicMock()
        self.token_repository.alias = "central"
        self.token_repository.create_digest.return_value = True

    def _create(self, *, atomic_context=nullcontext()):
        return create_signup_request_with_verification_token(
            self.data,
            ttl=timedelta(hours=2),
            key_ring=self.key_ring,
            alias="central",
            signup_repository=self.signup_repository,
            token_repository=self.token_repository,
            atomic_context=atomic_context,
            token_factory=lambda _size: "s" * 43,
        )

    def test_request_event_and_token_digest_share_one_outer_transaction(self):
        atomic = MagicMock()
        atomic.__enter__.return_value = atomic
        atomic.__exit__.return_value = False

        pending = self._create(atomic_context=atomic)

        atomic.__enter__.assert_called_once()
        atomic.__exit__.assert_called_once()
        self.assertEqual(pending.signup_request_id, "request-reference")
        self.assertEqual(pending.token, f"v1.current.{('s' * 43)}")
        self.assertNotIn(pending.token, repr(pending))
        self.assertNotIn(pending.signup_request_id, repr(pending))

        persisted = self.token_repository.create_digest.call_args.kwargs
        self.assertEqual(persisted["signup_request_id"], "request-reference")
        self.assertEqual(len(persisted["token_digest"]), 64)
        self.assertNotEqual(persisted["token_digest"], pending.token)
        self.assertNotIn("token", persisted)
        self.assertNotIn("raw_token", persisted)

    def test_alias_mismatch_fails_before_signup_or_token_write(self):
        self.token_repository.alias = "tenant"

        with self.assertRaises(EmailVerificationConfigurationError):
            self._create()

        self.signup_repository.account_exists.assert_not_called()
        self.signup_repository.create_inactive_user.assert_not_called()
        self.signup_repository.create_signup_request.assert_not_called()
        self.signup_repository.append_submitted_event.assert_not_called()
        self.token_repository.create_digest.assert_not_called()

    def test_token_issuance_failure_rolls_back_outer_signup_transaction(self):
        self.token_repository.create_digest.return_value = False
        atomic = MagicMock()
        atomic.__enter__.return_value = atomic
        atomic.__exit__.return_value = False

        with self.assertRaises(SignupEmailVerificationTokenIssuanceRejected):
            self._create(atomic_context=atomic)

        exit_args = atomic.__exit__.call_args.args
        self.assertIs(
            exit_args[0],
            SignupEmailVerificationTokenIssuanceRejected,
        )
        self.signup_repository.append_submitted_event.assert_called_once()
        self.token_repository.revoke_unconsumed.assert_called_once()
        self.token_repository.create_digest.assert_called_once()

    def test_contract_excludes_activation_membership_and_invitation_writes(self):
        self._create()

        called_methods = {
            *(call[0] for call in self.signup_repository.method_calls),
            *(call[0] for call in self.token_repository.method_calls),
        }
        self.assertEqual(
            called_methods,
            {
                "account_exists",
                "create_inactive_user",
                "create_signup_request",
                "append_submitted_event",
                "revoke_unconsumed",
                "create_digest",
            },
        )
