from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from control.services.signup_runtime_readiness import (
    GMAIL_SMTP_HOST,
    GMAIL_SMTP_PORT,
    NAVER_SMTP_HOST,
    NAVER_SMTP_PORT,
    SUPPORTED_SMTP_HOST_PORTS,
    SMTP_BACKEND,
    signup_public_runtime_ready,
)


class SignupPublicRuntimeReadinessTests(SimpleTestCase):
    def _settings(self, **overrides):
        values = {
            "EMAIL_BACKEND": SMTP_BACKEND,
            "EMAIL_HOST": NAVER_SMTP_HOST,
            "EMAIL_PORT": NAVER_SMTP_PORT,
            "EMAIL_USE_TLS": True,
            "EMAIL_HOST_USER": "configured-user",
            "EMAIL_HOST_PASSWORD": "configured-secret",
            "DEFAULT_FROM_EMAIL": "service@example.com",
            "SITE_ORIGIN": "https://example.com",
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    @patch("control.services.signup_runtime_readiness.load_signup_email_verification_key_ring")
    @patch("control.services.signup_runtime_readiness.load_signup_verification_outbox_config")
    def test_ready_requires_valid_verification_and_smtp_configuration(
        self,
        outbox_config,
        key_ring,
    ):
        outbox_config.return_value = SimpleNamespace(
            verification_url="https://example.com/signup/verify/"
        )
        self.assertTrue(
            signup_public_runtime_ready(
                settings_obj=self._settings(),
                environ={},
            )
        )
        outbox_config.assert_called_once()
        key_ring.assert_called_once()

    @patch("control.services.signup_runtime_readiness.load_signup_email_verification_key_ring")
    @patch("control.services.signup_runtime_readiness.load_signup_verification_outbox_config")
    def test_placeholder_or_missing_smtp_values_fail_closed(self, outbox_config, key_ring):
        outbox_config.return_value = SimpleNamespace(
            verification_url="https://example.com/signup/verify/"
        )
        invalid = (
            {"EMAIL_BACKEND": "django.core.mail.backends.console.EmailBackend"},
            {"EMAIL_HOST": "smtp.example.com"},
            {"EMAIL_PORT": 465},
            {"EMAIL_HOST_USER": ""},
            {"EMAIL_HOST_PASSWORD": ""},
            {"DEFAULT_FROM_EMAIL": "noreply@geoflow.local"},
            {"EMAIL_USE_TLS": False},
        )
        for values in invalid:
            with self.subTest(values=values):
                self.assertFalse(
                    signup_public_runtime_ready(
                        settings_obj=self._settings(**values),
                        environ={},
                    )
                )

    @patch(
        "control.services.signup_runtime_readiness.load_signup_verification_outbox_config",
        side_effect=Exception("should be narrowed by production implementation"),
    )
    def test_unexpected_exception_is_not_silently_swallowed(self, outbox_config):
        with self.assertRaises(Exception):
            signup_public_runtime_ready(
                settings_obj=self._settings(),
                environ={},
            )


class SignupMailProcessorAlignmentTests(SimpleTestCase):
    def test_runtime_providers_include_naver_and_gmail_starttls(self):
        source = __import__(
            "inspect"
        ).getsource(signup_public_runtime_ready)
        self.assertIn("SUPPORTED_SMTP_HOST_PORTS.get(host.lower())", source)
        self.assertEqual(NAVER_SMTP_HOST, "smtp.naver.com")
        self.assertEqual(NAVER_SMTP_PORT, 587)
        self.assertEqual(GMAIL_SMTP_HOST, "smtp.gmail.com")
        self.assertEqual(GMAIL_SMTP_PORT, 587)
        self.assertEqual(
            SUPPORTED_SMTP_HOST_PORTS,
            {"smtp.naver.com": 587, "smtp.gmail.com": 587},
        )

    @patch("control.services.signup_runtime_readiness.load_signup_email_verification_key_ring")
    @patch("control.services.signup_runtime_readiness.load_signup_verification_outbox_config")
    def test_gmail_smtp_runtime_is_ready(self, outbox_config, key_ring):
        outbox_config.return_value = SimpleNamespace(
            verification_url="https://example.com/signup/verify/"
        )
        settings_obj = SimpleNamespace(
            EMAIL_BACKEND=SMTP_BACKEND,
            EMAIL_HOST=GMAIL_SMTP_HOST,
            EMAIL_PORT=GMAIL_SMTP_PORT,
            EMAIL_HOST_USER="sender@gmail.com",
            EMAIL_HOST_PASSWORD="app-password",
            DEFAULT_FROM_EMAIL="sender@gmail.com",
            EMAIL_USE_TLS=True,
            EMAIL_USE_SSL=False,
            SITE_ORIGIN="https://example.com",
            SIGNUP_EMAIL_VERIFICATION_ACTIVE_KEY_ID="active",
            SIGNUP_EMAIL_VERIFICATION_HMAC_KEYS_JSON="configured",
            ENABLE_SIGNUP_EMAIL_VERIFICATION_OUTBOX=True,
        )
        self.assertTrue(signup_public_runtime_ready(settings_obj=settings_obj, environ={}))


class SignupHttpsReadinessTests(SimpleTestCase):
    @patch("control.services.signup_runtime_readiness.load_signup_email_verification_key_ring")
    @patch("control.services.signup_runtime_readiness.load_signup_verification_outbox_config")
    def test_non_debug_verification_url_requires_https(self, outbox_config, key_ring):
        settings_obj = SimpleNamespace(
            DEBUG=False,
            EMAIL_BACKEND=SMTP_BACKEND,
            EMAIL_HOST=NAVER_SMTP_HOST,
            EMAIL_PORT=NAVER_SMTP_PORT,
            EMAIL_USE_TLS=True,
            EMAIL_HOST_USER="configured-user",
            EMAIL_HOST_PASSWORD="configured-secret",
            DEFAULT_FROM_EMAIL="service@example.com",
            SITE_ORIGIN="https://example.com",
        )
        outbox_config.return_value = SimpleNamespace(
            verification_url="http://example.com/signup/verify/"
        )
        self.assertFalse(
            signup_public_runtime_ready(settings_obj=settings_obj, environ={})
        )

        settings_obj.DEBUG = True
        settings_obj.SITE_ORIGIN = "http://example.com"
        self.assertTrue(
            signup_public_runtime_ready(settings_obj=settings_obj, environ={})
        )

class SignupVerificationOriginBoundaryTests(SimpleTestCase):
    @patch("control.services.signup_runtime_readiness.load_signup_email_verification_key_ring")
    @patch("control.services.signup_runtime_readiness.load_signup_verification_outbox_config")
    def test_external_or_wrong_path_verification_url_fails_closed(self, outbox_config, key_ring):
        settings_obj = SimpleNamespace(
            DEBUG=False,
            EMAIL_BACKEND=SMTP_BACKEND,
            EMAIL_HOST=NAVER_SMTP_HOST,
            EMAIL_PORT=NAVER_SMTP_PORT,
            EMAIL_USE_TLS=True,
            EMAIL_HOST_USER="configured-user",
            EMAIL_HOST_PASSWORD="configured-secret",
            DEFAULT_FROM_EMAIL="service@example.com",
            SITE_ORIGIN="https://example.com",
        )
        for url in (
            "https://attacker.invalid/signup/verify/",
            "https://example.com/not-verify/",
            "https://example.com/signup/verify/?next=elsewhere",
        ):
            with self.subTest(url=url):
                outbox_config.return_value = SimpleNamespace(verification_url=url)
                self.assertFalse(signup_public_runtime_ready(settings_obj=settings_obj, environ={}))
    @patch("control.services.signup_runtime_readiness.load_signup_email_verification_key_ring")
    @patch("control.services.signup_runtime_readiness.load_signup_verification_outbox_config")
    def test_site_origin_must_be_clean_origin_without_path_or_userinfo(self, outbox_config, key_ring):
        outbox_config.return_value = SimpleNamespace(
            verification_url="https://example.com/signup/verify/"
        )
        base = dict(
            DEBUG=False,
            EMAIL_BACKEND=SMTP_BACKEND,
            EMAIL_HOST=NAVER_SMTP_HOST,
            EMAIL_PORT=NAVER_SMTP_PORT,
            EMAIL_USE_TLS=True,
            EMAIL_HOST_USER="configured-user",
            EMAIL_HOST_PASSWORD="configured-password",
            DEFAULT_FROM_EMAIL="service@example.com",
        )
        for origin in (
            "https://example.com/base",
            "https://user@example.com",
            "https://example.com/?x=1",
        ):
            with self.subTest(origin=origin):
                settings_obj = SimpleNamespace(**base, SITE_ORIGIN=origin)
                self.assertFalse(
                    signup_public_runtime_ready(settings_obj=settings_obj, environ={})
                )

