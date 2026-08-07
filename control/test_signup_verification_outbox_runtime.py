from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from control.services.signup_verification_outbox_config import (
    load_signup_verification_outbox_config,
)
from control.services.signup_verification_outbox_runtime import (
    process_next_signup_verification_outbox_item,
)
from control.services.signup_verification_outbox_service import (
    SignupVerificationDeliveryClaim,
)
from control.services.signup_verification_outbox_worker import (
    SignupVerificationDeliveryOutcome,
)
from control.services.signup_verification_service import (
    EmailVerificationConfigurationError,
)
from control.services.signup_verification_token_service import (
    HmacSha256VerificationKeyRing,
)


NOW = datetime(2026, 8, 7, 0, 0, tzinfo=timezone.utc)


class SignupVerificationOutboxConfigTests(TestCase):
    def test_valid_configuration_loads_without_inventing_runtime_values(self):
        config = load_signup_verification_outbox_config(
            settings_obj=SimpleNamespace(
                ENABLE_SIGNUP_EMAIL_VERIFICATION_OUTBOX=True,
                SIGNUP_EMAIL_VERIFICATION_URL=(
                    "https://example.invalid/signup/verify/"
                ),
                SIGNUP_EMAIL_VERIFICATION_TTL_SECONDS=3600,
                SIGNUP_EMAIL_VERIFICATION_OUTBOX_LEASE_SECONDS=120,
                SIGNUP_EMAIL_VERIFICATION_OUTBOX_RETRY_SECONDS=600,
                EMAIL_TIMEOUT=30,
            )
        )

        self.assertEqual(config.token_ttl, timedelta(seconds=3600))
        self.assertEqual(config.lease_for, timedelta(seconds=120))
        self.assertEqual(config.retry_delay, timedelta(seconds=600))
        self.assertEqual(config.email_timeout, timedelta(seconds=30))

    def test_missing_invalid_or_fragment_url_fails_closed(self):
        invalid_settings = (
            SimpleNamespace(),
            SimpleNamespace(
                ENABLE_SIGNUP_EMAIL_VERIFICATION_OUTBOX=True,
                SIGNUP_EMAIL_VERIFICATION_URL="/signup/verify/",
                SIGNUP_EMAIL_VERIFICATION_TTL_SECONDS=3600,
                SIGNUP_EMAIL_VERIFICATION_OUTBOX_LEASE_SECONDS=120,
                SIGNUP_EMAIL_VERIFICATION_OUTBOX_RETRY_SECONDS=600,
                EMAIL_TIMEOUT=30,
            ),
            SimpleNamespace(
                ENABLE_SIGNUP_EMAIL_VERIFICATION_OUTBOX=True,
                SIGNUP_EMAIL_VERIFICATION_URL=(
                    "https://example.invalid/signup/verify/#token=x"
                ),
                SIGNUP_EMAIL_VERIFICATION_TTL_SECONDS=3600,
                SIGNUP_EMAIL_VERIFICATION_OUTBOX_LEASE_SECONDS=120,
                SIGNUP_EMAIL_VERIFICATION_OUTBOX_RETRY_SECONDS=600,
                EMAIL_TIMEOUT=30,
            ),
        )
        for settings_obj in invalid_settings:
            with self.subTest(settings_obj=settings_obj):
                with self.assertRaises(EmailVerificationConfigurationError):
                    load_signup_verification_outbox_config(
                        settings_obj=settings_obj
                    )

    def test_email_timeout_is_required_and_must_be_shorter_than_lease(self):
        base = dict(
            ENABLE_SIGNUP_EMAIL_VERIFICATION_OUTBOX=True,
            SIGNUP_EMAIL_VERIFICATION_URL=(
                "https://example.invalid/signup/verify/"
            ),
            SIGNUP_EMAIL_VERIFICATION_TTL_SECONDS=3600,
            SIGNUP_EMAIL_VERIFICATION_OUTBOX_LEASE_SECONDS=120,
            SIGNUP_EMAIL_VERIFICATION_OUTBOX_RETRY_SECONDS=600,
        )
        for timeout in (None, 120, 121):
            with self.subTest(timeout=timeout):
                values = dict(base)
                if timeout is not None:
                    values["EMAIL_TIMEOUT"] = timeout
                with self.assertRaises(EmailVerificationConfigurationError):
                    load_signup_verification_outbox_config(
                        settings_obj=SimpleNamespace(**values)
                    )


class SignupVerificationOutboxRuntimeTests(TestCase):
    def setUp(self):
        self.key_ring = HmacSha256VerificationKeyRing(
            active_key_id="current",
            keys={"current": b"k" * 32},
        )

    @patch(
        "control.services.signup_verification_outbox_runtime."
        "process_signup_verification_delivery_claim",
        return_value=SignupVerificationDeliveryOutcome(status="delivered"),
    )
    @patch(
        "control.services.signup_verification_outbox_runtime."
        "claim_next_signup_email_verification_delivery"
    )
    def test_runtime_processes_at_most_one_claim(
        self,
        claim_next,
        process_claim,
    ):
        claim_next.return_value = SignupVerificationDeliveryClaim(
            outbox_id="outbox-reference",
            signup_request_id="request-reference",
            email="applicant@example.com",
            lease_id="lease-reference",
            attempt_count=1,
            claim_expires_at=NOW + timedelta(minutes=2),
        )

        result = process_next_signup_verification_outbox_item(
            verification_url="https://example.invalid/signup/verify/",
            ttl=timedelta(hours=1),
            lease_for=timedelta(minutes=2),
            retry_delay=timedelta(minutes=10),
            email_timeout=timedelta(seconds=30),
            key_ring=self.key_ring,
            clock=lambda: NOW,
        )

        self.assertTrue(result.claimed)
        self.assertEqual(result.outcome, "delivered")
        claim_next.assert_called_once()
        process_claim.assert_called_once()

    @patch(
        "control.services.signup_verification_outbox_runtime."
        "claim_next_signup_email_verification_delivery",
        return_value=None,
    )
    def test_runtime_stops_without_delivery_when_queue_is_empty(self, claim_next):
        result = process_next_signup_verification_outbox_item(
            verification_url="https://example.invalid/signup/verify/",
            ttl=timedelta(hours=1),
            lease_for=timedelta(minutes=2),
            retry_delay=timedelta(minutes=10),
            email_timeout=timedelta(seconds=30),
            key_ring=self.key_ring,
            clock=lambda: NOW,
        )

        self.assertFalse(result.claimed)
        self.assertIsNone(result.outcome)
        claim_next.assert_called_once()


class SignupVerificationOutboxEnvironmentConfigTests(TestCase):
    def test_environment_values_load_without_settings_module_wiring(self):
        config = load_signup_verification_outbox_config(
            settings_obj=SimpleNamespace(),
            environ={
                "ENABLE_SIGNUP_EMAIL_VERIFICATION_OUTBOX": "1",
                "SIGNUP_EMAIL_VERIFICATION_URL": (
                    "https://example.invalid/signup/verify/"
                ),
                "SIGNUP_EMAIL_VERIFICATION_TTL_SECONDS": "3600",
                "SIGNUP_EMAIL_VERIFICATION_OUTBOX_LEASE_SECONDS": "120",
                "SIGNUP_EMAIL_VERIFICATION_OUTBOX_RETRY_SECONDS": "600",
                "EMAIL_TIMEOUT": "30",
            },
        )

        self.assertEqual(config.token_ttl, timedelta(hours=1))
        self.assertEqual(config.lease_for, timedelta(seconds=120))
        self.assertEqual(config.retry_delay, timedelta(seconds=600))
        self.assertEqual(config.email_timeout, timedelta(seconds=30))
