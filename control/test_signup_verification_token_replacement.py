from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from inspect import getsource
from unittest import TestCase
from unittest.mock import MagicMock

from control.services.signup_verification_token_service import (
    CentralSignupEmailVerificationTokenRepository,
    HmacSha256VerificationKeyRing,
    issue_signup_email_verification_token,
)


NOW = datetime(2026, 8, 7, 0, 0, tzinfo=timezone.utc)


class SignupVerificationTokenReplacementTests(TestCase):
    def setUp(self):
        self.repository = MagicMock()
        self.repository.create_digest.return_value = True
        self.key_ring = HmacSha256VerificationKeyRing(
            active_key_id="current",
            keys={"current": b"k" * 32},
        )

    def test_issue_revokes_previous_before_creating_new_digest(self):
        issued = issue_signup_email_verification_token(
            signup_request_id="request-reference",
            ttl=timedelta(hours=1),
            key_ring=self.key_ring,
            repository=self.repository,
            clock=lambda: NOW,
            token_factory=lambda _size: "s" * 43,
            atomic_context=nullcontext(),
        )

        method_names = [call[0] for call in self.repository.method_calls]
        self.assertEqual(method_names[:2], ["revoke_unconsumed", "create_digest"])
        revoke = self.repository.revoke_unconsumed.call_args.kwargs
        self.assertEqual(revoke["signup_request_id"], "request-reference")
        self.assertEqual(revoke["revoked_at"], NOW)
        self.assertNotIn(issued.token, repr(self.repository.create_digest.call_args))

    def test_repository_revocation_preserves_timestamp_constraint(self):
        source = getsource(
            CentralSignupEmailVerificationTokenRepository.revoke_unconsumed
        )

        self.assertIn("GREATEST(%s, created_at)", source)
        self.assertIn("consumed_at IS NULL", source)
        self.assertIn("revoked_at IS NULL", source)

    def test_repository_consume_rejects_revoked_tokens(self):
        source = getsource(
            CentralSignupEmailVerificationTokenRepository.consume_digest
        )

        self.assertIn("verification_token.revoked_at IS NULL", source)

    def test_repository_insert_contains_digest_but_no_raw_token_column(self):
        source = getsource(
            CentralSignupEmailVerificationTokenRepository.create_digest
        )

        self.assertIn("token_digest", source)
        self.assertIn("consumed_at, revoked_at, created_at", source)
        self.assertNotIn("raw_token", source)
        self.assertNotIn("token_value", source)
