from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock
from urllib.parse import urlsplit

from control.services.account_password_reset_delivery import (
    AccountPasswordResetConfigurationError,
    AccountPasswordResetEmailDeliveryError,
    build_account_password_reset_link,
    load_account_password_reset_delivery_config,
    send_account_password_reset_email,
)


class AccountPasswordResetDeliveryTests(TestCase):
    def test_raw_token_is_fragment_only(self):
        token = "pr1.current." + ("s" * 43)
        link = build_account_password_reset_link(
            "https://example.test/password/reset/",
            token,
        )
        parts = urlsplit(link)
        self.assertEqual(parts.path, "/password/reset/")
        self.assertEqual(parts.query, "")
        self.assertIn("token=", parts.fragment)
        self.assertNotIn(token, parts.path)
        self.assertNotIn(token, parts.query)

    def test_config_defaults_to_site_origin_and_bounded_security_values(self):
        settings_obj = SimpleNamespace(
            SITE_ORIGIN="https://example.test",
            SIGNUP_EMAIL_VERIFICATION_OUTBOX_LEASE_SECONDS=120,
            SIGNUP_EMAIL_VERIFICATION_OUTBOX_RETRY_SECONDS=300,
            SIGNUP_EMAIL_VERIFICATION_OUTBOX_MAX_ATTEMPTS=5,
        )
        config = load_account_password_reset_delivery_config(
            settings_obj=settings_obj,
            environ={},
        )
        self.assertEqual(config.reset_url, "https://example.test/password/reset/")
        self.assertEqual(int(config.token_ttl.total_seconds()), 3600)
        self.assertEqual(int(config.request_cooldown.total_seconds()), 600)
        self.assertGreater(config.lease_for, config.email_timeout)

    def test_site_origin_environment_overrides_stale_setting_fallback(self):
        settings_obj = SimpleNamespace(
            SITE_ORIGIN="http://192.168.0.19:8000",
            SIGNUP_EMAIL_VERIFICATION_OUTBOX_LEASE_SECONDS=120,
            SIGNUP_EMAIL_VERIFICATION_OUTBOX_RETRY_SECONDS=300,
            SIGNUP_EMAIL_VERIFICATION_OUTBOX_MAX_ATTEMPTS=5,
        )
        config = load_account_password_reset_delivery_config(
            settings_obj=settings_obj,
            environ={"SITE_ORIGIN": "https://geoflow.co.kr"},
        )
        self.assertEqual(config.reset_url, "https://geoflow.co.kr/password/reset/")

    def test_config_rejects_non_http_reset_url(self):
        settings_obj = SimpleNamespace(SITE_ORIGIN="javascript:bad")
        with self.assertRaises(AccountPasswordResetConfigurationError):
            load_account_password_reset_delivery_config(
                settings_obj=settings_obj,
                environ={},
            )

    def test_mail_sender_gets_single_recipient_and_sanitizes_failure(self):
        mail_sender = MagicMock(return_value=1)
        token = "pr1.current." + ("s" * 43)
        link = build_account_password_reset_link(
            "https://example.test/password/reset/",
            token,
        )
        send_account_password_reset_email(
            to_email="user@example.test",
            reset_link=link,
            expires_at=datetime(2026, 8, 10, 2, 0, tzinfo=timezone.utc),
            mail_sender=mail_sender,
            settings_obj=SimpleNamespace(DEFAULT_FROM_EMAIL="no-reply@example.test"),
        )
        args = mail_sender.call_args.args
        self.assertEqual(args[3], ["user@example.test"])
        self.assertIn(link, args[1])

        failing_sender = MagicMock(side_effect=RuntimeError("provider secret detail"))
        with self.assertRaises(AccountPasswordResetEmailDeliveryError) as caught:
            send_account_password_reset_email(
                to_email="user@example.test",
                reset_link=link,
                expires_at=datetime(2026, 8, 10, 2, 0, tzinfo=timezone.utc),
                mail_sender=failing_sender,
                settings_obj=SimpleNamespace(DEFAULT_FROM_EMAIL="no-reply@example.test"),
            )
        self.assertNotIn("provider secret detail", str(caught.exception))
