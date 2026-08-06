from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from inspect import getsource
from unittest import TestCase
from unittest.mock import MagicMock

from control.services.signup_verification_service import (
    EmailVerificationConfigurationError,
    EmailVerificationGrant,
)
from control.services.signup_verification_token_service import (
    CentralSignupEmailVerificationTokenRepository,
    DatabaseSignupEmailVerificationTokenVerifier,
    HmacSha256VerificationKeyRing,
    SIGNUP_EMAIL_VERIFICATION_DIGEST_ALGORITHM,
    SIGNUP_EMAIL_VERIFICATION_PURPOSE,
    SignupEmailVerificationTokenIssuanceRejected,
    issue_signup_email_verification_token,
    verify_signup_email_with_database_token,
)


class SignupEmailVerificationTokenServiceTests(TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 6, 9, 0, tzinfo=timezone.utc)
        self.key_ring = HmacSha256VerificationKeyRing(
            active_key_id="current",
            keys={
                "current": b"c" * 32,
                "previous": b"p" * 32,
            },
        )
        self.repository = MagicMock()
        self.repository.create_digest.return_value = True

    def test_issue_persists_digest_only_and_returns_raw_token_once(self):
        issued = issue_signup_email_verification_token(
            signup_request_id="request-reference",
            ttl=timedelta(hours=2),
            key_ring=self.key_ring,
            repository=self.repository,
            clock=lambda: self.now,
            token_factory=lambda _size: "s" * 43,
            atomic_context=nullcontext(),
        )

        self.assertEqual(issued.token, f"v1.current.{('s' * 43)}")
        self.assertEqual(issued.expires_at, self.now + timedelta(hours=2))
        persisted = self.repository.create_digest.call_args.kwargs
        self.assertEqual(persisted["signup_request_id"], "request-reference")
        self.assertEqual(persisted["purpose"], SIGNUP_EMAIL_VERIFICATION_PURPOSE)
        self.assertEqual(
            persisted["digest_algorithm"],
            SIGNUP_EMAIL_VERIFICATION_DIGEST_ALGORITHM,
        )
        self.assertEqual(persisted["digest_key_id"], "current")
        self.assertEqual(len(persisted["token_digest"]), 64)
        self.assertNotEqual(persisted["token_digest"], issued.token)
        self.assertNotIn("token", persisted)
        self.assertNotIn("raw_token", persisted)

    def test_issue_rejects_stale_or_ineligible_request_without_returning_token(self):
        self.repository.create_digest.return_value = False

        with self.assertRaises(SignupEmailVerificationTokenIssuanceRejected):
            issue_signup_email_verification_token(
                signup_request_id="request-reference",
                ttl=timedelta(hours=1),
                key_ring=self.key_ring,
                repository=self.repository,
                clock=lambda: self.now,
                token_factory=lambda _size: "s" * 43,
                atomic_context=nullcontext(),
            )

    def test_issue_rejects_non_positive_ttl_before_persistence(self):
        for ttl in (timedelta(0), timedelta(seconds=-1)):
            with self.assertRaises(ValueError):
                issue_signup_email_verification_token(
                    signup_request_id="request-reference",
                    ttl=ttl,
                    key_ring=self.key_ring,
                    repository=self.repository,
                    clock=lambda: self.now,
                    token_factory=lambda _size: "s" * 43,
                    atomic_context=nullcontext(),
                )

        self.repository.create_digest.assert_not_called()

    def test_issue_rejects_non_url_safe_factory_output(self):
        with self.assertRaises(ValueError):
            issue_signup_email_verification_token(
                signup_request_id="request-reference",
                ttl=timedelta(hours=1),
                key_ring=self.key_ring,
                repository=self.repository,
                clock=lambda: self.now,
                token_factory=lambda _size: "not valid token material",
                atomic_context=nullcontext(),
            )

        self.repository.create_digest.assert_not_called()

    def test_consume_maps_valid_token_to_digest_bound_grant(self):
        expected = EmailVerificationGrant(
            user_id="user-reference",
            signup_request_id="request-reference",
        )
        self.repository.consume_digest.return_value = expected
        verifier = DatabaseSignupEmailVerificationTokenVerifier(
            key_ring=self.key_ring,
            repository=self.repository,
            clock=lambda: self.now,
        )

        grant = verifier.consume(f"v1.current.{('s' * 43)}")

        self.assertEqual(grant, expected)
        consumed = self.repository.consume_digest.call_args.kwargs
        self.assertEqual(consumed["purpose"], SIGNUP_EMAIL_VERIFICATION_PURPOSE)
        self.assertEqual(
            consumed["digest_algorithm"],
            SIGNUP_EMAIL_VERIFICATION_DIGEST_ALGORITHM,
        )
        self.assertEqual(consumed["digest_key_id"], "current")
        self.assertEqual(consumed["consumed_at"], self.now)
        self.assertEqual(len(consumed["token_digest"]), 64)
        self.assertNotIn("token", consumed)

    def test_previous_rotation_key_remains_verifiable_while_configured(self):
        self.repository.consume_digest.return_value = EmailVerificationGrant(
            user_id="user-reference",
            signup_request_id="request-reference",
        )
        verifier = DatabaseSignupEmailVerificationTokenVerifier(
            key_ring=self.key_ring,
            repository=self.repository,
            clock=lambda: self.now,
        )

        verifier.consume(f"v1.previous.{('s' * 43)}")

        consumed = self.repository.consume_digest.call_args.kwargs
        self.assertEqual(consumed["digest_key_id"], "previous")

    def test_malformed_or_unknown_key_token_fails_without_database_write(self):
        verifier = DatabaseSignupEmailVerificationTokenVerifier(
            key_ring=self.key_ring,
            repository=self.repository,
            clock=lambda: self.now,
        )

        for token in (
            "",
            "v1.current.short",
            f"v2.current.{('s' * 43)}",
            f"v1.unknown.{('s' * 43)}",
            f"v1.bad.key.{('s' * 43)}",
        ):
            with self.subTest(token=token):
                self.assertIsNone(verifier.consume(token))

        self.repository.consume_digest.assert_not_called()

    def test_key_ring_requires_url_safe_ids_and_256_bit_keys(self):
        with self.assertRaises(ValueError):
            HmacSha256VerificationKeyRing(
                active_key_id="bad key",
                keys={"bad key": b"k" * 32},
            )
        with self.assertRaises(ValueError):
            HmacSha256VerificationKeyRing(
                active_key_id="current",
                keys={"current": b"short"},
            )
        with self.assertRaises(ValueError):
            HmacSha256VerificationKeyRing(
                active_key_id="missing",
                keys={"current": b"k" * 32},
            )

    def test_repository_sql_enforces_expiry_single_use_binding_and_inactive_state(self):
        source = getsource(CentralSignupEmailVerificationTokenRepository.consume_digest)

        for contract in (
            "verification_token.consumed_at IS NULL",
            "verification_token.expires_at > %s",
            "verification_token.purpose=%s",
            "verification_token.digest_algorithm=%s",
            "verification_token.digest_key_id=%s",
            "verification_token.token_digest=%s",
            "signup_request.status='pending_email_verification'",
            "signup_user.email_verified=FALSE",
            "signup_user.is_active=FALSE",
            "RETURNING signup_request.user_id, signup_request.id",
        ):
            self.assertIn(contract, source)

        self.assertNotIn("password_hash", source)
        self.assertNotIn("join_requests", source)
        self.assertNotIn("user_group_map", source)
        self.assertNotIn("employee_profile", source)

    def test_repository_insert_has_no_raw_token_column(self):
        source = getsource(CentralSignupEmailVerificationTokenRepository.create_digest)

        for contract in (
            "signup_request.status='pending_email_verification'",
            "signup_user.email_verified=FALSE",
            "signup_user.is_active=FALSE",
            "RETURNING id",
            "token_digest",
        ):
            self.assertIn(contract, source)
        self.assertNotIn("raw_token", source)
        self.assertNotIn("token_value", source)
        self.assertNotIn("password_hash", source)

    def test_orchestrator_uses_one_alias_for_token_and_state_writes(self):
        token_repository = MagicMock()
        token_repository.alias = "central"
        token_repository.consume_digest.return_value = EmailVerificationGrant(
            user_id="user-reference",
            signup_request_id="request-reference",
        )
        verification_repository = MagicMock()
        verification_repository.alias = "central"
        verification_repository.transition_request_to_pending_approval.return_value = True
        verification_repository.mark_email_verified.return_value = True

        verify_signup_email_with_database_token(
            f"v1.current.{('s' * 43)}",
            key_ring=self.key_ring,
            alias="central",
            token_repository=token_repository,
            verification_repository=verification_repository,
            atomic_context=nullcontext(),
        )

        token_repository.consume_digest.assert_called_once()
        verification_repository.transition_request_to_pending_approval.assert_called_once()
        verification_repository.mark_email_verified.assert_called_once()
        verification_repository.append_verified_event.assert_called_once()

    def test_orchestrator_rejects_alias_mismatch_before_any_write(self):
        token_repository = MagicMock()
        token_repository.alias = "tenant"
        verification_repository = MagicMock()
        verification_repository.alias = "central"

        with self.assertRaises(EmailVerificationConfigurationError):
            verify_signup_email_with_database_token(
                f"v1.current.{('s' * 43)}",
                key_ring=self.key_ring,
                alias="central",
                token_repository=token_repository,
                verification_repository=verification_repository,
                atomic_context=nullcontext(),
            )

        token_repository.consume_digest.assert_not_called()
        verification_repository.transition_request_to_pending_approval.assert_not_called()
        verification_repository.mark_email_verified.assert_not_called()
        verification_repository.append_verified_event.assert_not_called()
