from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from control.services.signup_runtime_readiness import (
    SMTP_BACKEND,
    signup_public_runtime_ready,
)


class SignupPublicRuntimeReadinessTests(SimpleTestCase):
    def _settings(self, **overrides):
        values = {
            "EMAIL_BACKEND": SMTP_BACKEND,
            "EMAIL_HOST": "smtp.naver.com",
            "EMAIL_PORT": 587,
            "EMAIL_USE_TLS": True,
            "EMAIL_HOST_USER": "configured-user",
            "EMAIL_HOST_PASSWORD": "configured-secret",
            "DEFAULT_FROM_EMAIL": "service@example.com",
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
        invalid = (
            {"EMAIL_BACKEND": "django.core.mail.backends.console.EmailBackend"},
            {"EMAIL_HOST": "smtp.example.com"},
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
