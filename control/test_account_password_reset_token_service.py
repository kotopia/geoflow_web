from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from inspect import getsource
from unittest import TestCase
from unittest.mock import MagicMock

from control.services.account_password_reset_token_service import (
    ACCOUNT_PASSWORD_RESET_DIGEST_ALGORITHM,
    ACCOUNT_PASSWORD_RESET_PURPOSE,
    AccountPasswordResetTokenIssuanceRejected,
    CentralAccountPasswordResetTokenRepository,
    consume_account_password_reset_token,
    issue_account_password_reset_token,
)
from control.services.signup_verification_token_service import (
    HmacSha256VerificationKeyRing,
)


class AccountPasswordResetTokenServiceTests(TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 10, 1, 0, tzinfo=timezone.utc)
        self.key_ring = HmacSha256VerificationKeyRing(
            active_key_id="current",
            keys={"current": b"c" * 32, "previous": b"p" * 32},
        )
        self.repository = MagicMock()
        self.repository.alias = "central"
        self.repository.create_digest.return_value = True

    def test_issue_returns_raw_once_but_persists_digest_only(self):
        issued = issue_account_password_reset_token(
            user_id="user-reference",
            ttl=timedelta(hours=1),
            key_ring=self.key_ring,
            repository=self.repository,
            clock=lambda: self.now,
            token_factory=lambda _size: "s" * 43,
            atomic_context=nullcontext(),
        )

        self.assertEqual(issued.token, f"pr1.current.{('s' * 43)}")
        self.assertNotIn(issued.token, repr(issued))
        self.repository.revoke_unconsumed.assert_called_once()
        persisted = self.repository.create_digest.call_args.kwargs
        self.assertEqual(persisted["user_id"], "user-reference")
        self.assertEqual(persisted["purpose"], ACCOUNT_PASSWORD_RESET_PURPOSE)
        self.assertEqual(persisted["digest_algorithm"], ACCOUNT_PASSWORD_RESET_DIGEST_ALGORITHM)
        self.assertEqual(persisted["digest_key_id"], "current")
        self.assertEqual(len(persisted["token_digest"]), 64)
        self.assertNotEqual(persisted["token_digest"], issued.token)
        self.assertNotIn("token", persisted)
        self.assertNotIn("raw_token", persisted)

    def test_issue_rejects_ineligible_account_without_returning_grant(self):
        self.repository.create_digest.return_value = False
        with self.assertRaises(AccountPasswordResetTokenIssuanceRejected):
            issue_account_password_reset_token(
                user_id="user-reference",
                ttl=timedelta(hours=1),
                key_ring=self.key_ring,
                repository=self.repository,
                clock=lambda: self.now,
                token_factory=lambda _size: "s" * 43,
                atomic_context=nullcontext(),
            )

    def test_consume_maps_valid_token_to_digest_lookup(self):
        self.repository.consume_digest.return_value = "user-reference"
        token = f"pr1.current.{('s' * 43)}"
        result = consume_account_password_reset_token(
            token,
            key_ring=self.key_ring,
            repository=self.repository,
            clock=lambda: self.now,
        )
        self.assertEqual(result, "user-reference")
        consumed = self.repository.consume_digest.call_args.kwargs
        self.assertEqual(consumed["purpose"], ACCOUNT_PASSWORD_RESET_PURPOSE)
        self.assertEqual(consumed["digest_key_id"], "current")
        self.assertEqual(consumed["consumed_at"], self.now)
        self.assertEqual(len(consumed["token_digest"]), 64)
        self.assertNotIn("token", consumed)

    def test_previous_rotation_key_remains_verifiable(self):
        self.repository.consume_digest.return_value = "user-reference"
        consume_account_password_reset_token(
            f"pr1.previous.{('s' * 43)}",
            key_ring=self.key_ring,
            repository=self.repository,
            clock=lambda: self.now,
        )
        self.assertEqual(
            self.repository.consume_digest.call_args.kwargs["digest_key_id"],
            "previous",
        )

    def test_malformed_unknown_or_wrong_version_token_never_hits_database(self):
        for token in (
            "",
            "pr1.current.short",
            f"v1.current.{('s' * 43)}",
            f"pr1.unknown.{('s' * 43)}",
            f"pr1.bad.key.{('s' * 43)}",
        ):
            with self.subTest(token=token):
                self.assertIsNone(
                    consume_account_password_reset_token(
                        token,
                        key_ring=self.key_ring,
                        repository=self.repository,
                        clock=lambda: self.now,
                    )
                )
        self.repository.consume_digest.assert_not_called()

    def test_repository_consumption_enforces_expiry_replay_and_account_state(self):
        source = getsource(CentralAccountPasswordResetTokenRepository.consume_digest)
        for contract in (
            "reset_token.consumed_at IS NULL",
            "reset_token.revoked_at IS NULL",
            "reset_token.expires_at > %s",
            "reset_token.purpose=%s",
            "reset_token.digest_algorithm=%s",
            "reset_token.digest_key_id=%s",
            "reset_token.token_digest=%s",
            "account_user.is_active=TRUE",
            "account_user.email_verified=TRUE",
            "RETURNING reset_token.user_id",
        ):
            self.assertIn(contract, source)

    def test_repository_insert_requires_active_verified_password_account(self):
        source = getsource(CentralAccountPasswordResetTokenRepository.create_digest)
        for contract in (
            "account_user.is_active=TRUE",
            "account_user.email_verified=TRUE",
            "account_user.password_hash IS NOT NULL",
            "token_digest",
            "RETURNING id",
        ):
            self.assertIn(contract, source)
        self.assertNotIn("raw_token", source)
        self.assertNotIn("token_value", source)
