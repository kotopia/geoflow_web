from __future__ import annotations

from contextlib import nullcontext
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import Client, SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from control.services.account_password_reset_delivery import (
    AccountPasswordResetEmailDeliveryError,
    build_account_password_reset_link,
    load_account_password_reset_delivery_config,
    send_account_password_reset_email,
)
from control.services.account_password_reset_outbox_service import (
    queue_account_password_reset_request,
)
from control.services.account_password_reset_token_service import (
    ACCOUNT_PASSWORD_RESET_PURPOSE,
    consume_account_password_reset_token,
    issue_account_password_reset_token,
)
from control.services.signup_verification_token_service import (
    HmacSha256VerificationKeyRing,
)


class _FakeTokenRepository:
    alias = "default"

    def __init__(self):
        self.live = None
        self.revoked = 0
        self.created = None
        self.consumed = False

    def revoke_unconsumed(self, **kwargs):
        self.revoked += 1
        self.live = None
        return 1

    def create_digest(self, **kwargs):
        self.created = kwargs.copy()
        self.live = kwargs["token_digest"]
        return True

    def consume_digest(self, **kwargs):
        if self.consumed or self.live != kwargs["token_digest"]:
            return None
        self.consumed = True
        return "11111111-1111-1111-1111-111111111111"


class _FakeQueueRepository:
    alias = "default"

    def __init__(self, result=True):
        self.result = result
        self.calls = []

    def queue_for_email(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


class AccountPasswordResetTokenTests(SimpleTestCase):
    def setUp(self):
        self.key_ring = HmacSha256VerificationKeyRing(
            active_key_id="k1",
            keys={"k1": b"A" * 32},
        )

    def test_raw_token_is_not_persisted_and_replay_is_rejected(self):
        repository = _FakeTokenRepository()
        now = timezone.now()
        issued = issue_account_password_reset_token(
            user_id="11111111-1111-1111-1111-111111111111",
            ttl=timedelta(hours=1),
            key_ring=self.key_ring,
            repository=repository,
            clock=lambda: now,
            token_factory=lambda _size: "B" * 43,
            atomic_context=nullcontext(),
        )

        self.assertTrue(issued.token.startswith("pr1.k1."))
        self.assertEqual(repository.revoked, 1)
        self.assertEqual(repository.created["purpose"], ACCOUNT_PASSWORD_RESET_PURPOSE)
        self.assertNotEqual(repository.created["token_digest"], issued.token)
        self.assertEqual(len(repository.created["token_digest"]), 64)
        self.assertEqual(issued.expires_at, now + timedelta(hours=1))

        first = consume_account_password_reset_token(
            issued.token,
            key_ring=self.key_ring,
            repository=repository,
            clock=lambda: now + timedelta(minutes=1),
        )
        second = consume_account_password_reset_token(
            issued.token,
            key_ring=self.key_ring,
            repository=repository,
            clock=lambda: now + timedelta(minutes=2),
        )
        self.assertIsNotNone(first)
        self.assertIsNone(second)

    def test_reset_link_keeps_token_out_of_path_and_query(self):
        link = build_account_password_reset_link(
            "https://geoflow.co.kr/password/reset/",
            "pr1.k1." + "C" * 43,
        )
        self.assertTrue(link.startswith("https://geoflow.co.kr/password/reset/#token="))
        before_fragment = link.split("#", 1)[0]
        self.assertNotIn("pr1.k1", before_fragment)

    def test_mail_failure_is_sanitized(self):
        def failing_sender(*args, **kwargs):
            raise RuntimeError("sensitive smtp detail")

        with self.assertRaises(AccountPasswordResetEmailDeliveryError) as caught:
            send_account_password_reset_email(
                to_email="person@example.com",
                reset_link="https://geoflow.co.kr/password/reset/#token=redacted",
                expires_at=timezone.now() + timedelta(hours=1),
                mail_sender=failing_sender,
            )
        self.assertNotIn("smtp", str(caught.exception).lower())
        self.assertNotIn("person@example.com", str(caught.exception))

    def test_delivery_config_reuses_existing_safe_worker_defaults(self):
        settings_obj = SimpleNamespace(
            SITE_ORIGIN="https://geoflow.co.kr",
            SIGNUP_EMAIL_VERIFICATION_OUTBOX_LEASE_SECONDS=120,
            SIGNUP_EMAIL_VERIFICATION_OUTBOX_RETRY_SECONDS=300,
            SIGNUP_EMAIL_VERIFICATION_OUTBOX_MAX_ATTEMPTS=5,
        )
        config = load_account_password_reset_delivery_config(
            settings_obj=settings_obj,
            environ={},
        )
        self.assertEqual(config.reset_url, "https://geoflow.co.kr/password/reset/")
        self.assertEqual(config.token_ttl, timedelta(hours=1))
        self.assertEqual(config.request_cooldown, timedelta(minutes=10))
        self.assertEqual(config.lease_for, timedelta(seconds=120))
        self.assertEqual(config.retry_delay, timedelta(seconds=300))
        self.assertEqual(config.max_attempts, 5)

    def test_queue_normalizes_email_and_applies_cooldown_without_exposing_result(self):
        repository = _FakeQueueRepository(result=False)
        now = timezone.now()
        with patch(
            "control.services.account_password_reset_outbox_service.transaction.atomic",
            return_value=nullcontext(),
        ):
            queued = queue_account_password_reset_request(
                "  Person@Example.COM ",
                cooldown=timedelta(minutes=10),
                repository=repository,
                clock=lambda: now,
            )
        self.assertFalse(queued)
        self.assertEqual(repository.calls[0]["email"], "person@example.com")
        self.assertEqual(repository.calls[0]["recent_cutoff"], now - timedelta(minutes=10))


@override_settings(SESSION_ENGINE="django.contrib.sessions.backends.signed_cookies")
class AccountPasswordResetRouteTests(SimpleTestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

    def test_forgot_request_remains_csrf_protected(self):
        response = self.client.post(
            reverse("password_forgot"),
            {"email": "person@example.com"},
        )
        self.assertEqual(response.status_code, 403)

    def test_reset_post_is_scoped_csrf_exempt_and_reaches_application(self):
        fake_config = SimpleNamespace(request_cooldown=timedelta(minutes=10))
        fake_key_ring = HmacSha256VerificationKeyRing(
            active_key_id="k1",
            keys={"k1": b"A" * 32},
        )
        with (
            patch(
                "control.views_password_reset.load_account_password_reset_delivery_config",
                return_value=fake_config,
            ),
            patch(
                "control.views_password_reset.load_signup_email_verification_key_ring",
                return_value=fake_key_ring,
            ),
            patch("control.views_password_reset.queue_account_password_reset_request"),
            patch("control.views_password_reset.reset_account_password_with_token") as reset,
        ):
            response = self.client.post(
                reverse("password_reset"),
                {
                    "token": "pr1.k1." + "D" * 43,
                    "new_password": "SafePassword-2026!",
                    "new_password2": "SafePassword-2026!",
                },
            )
        self.assertEqual(response.status_code, 200)
        reset.assert_called_once()
        self.assertContains(response, "비밀번호가 변경되었습니다")

    def test_reset_get_uses_fragment_bridge_and_never_cache(self):
        response = self.client.get(reverse("password_reset"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "window.location.hash")
        self.assertContains(response, "history.replaceState")
        self.assertIn("no-cache", response.headers.get("Cache-Control", ""))
