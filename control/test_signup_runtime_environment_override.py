from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from control.services.signup_runtime_readiness import (
    NAVER_SMTP_HOST,
    NAVER_SMTP_PORT,
    SMTP_BACKEND,
    signup_public_runtime_ready,
)


class SignupRuntimeEnvironmentOverrideTests(SimpleTestCase):
    @patch("control.services.signup_runtime_readiness.load_signup_email_verification_key_ring")
    @patch("control.services.signup_runtime_readiness.load_signup_verification_outbox_config")
    def test_production_environment_overrides_local_origin_and_sender_placeholders(
        self,
        outbox_config,
        key_ring,
    ):
        settings_obj = SimpleNamespace(
            DEBUG=False,
            EMAIL_BACKEND=SMTP_BACKEND,
            EMAIL_HOST=NAVER_SMTP_HOST,
            EMAIL_PORT=NAVER_SMTP_PORT,
            EMAIL_USE_TLS=True,
            EMAIL_HOST_USER="configured-user",
            EMAIL_HOST_PASSWORD="configured-secret",
            DEFAULT_FROM_EMAIL="noreply@geoflow.local",
            SITE_ORIGIN="http://192.168.0.19:8000",
        )
        outbox_config.return_value = SimpleNamespace(
            verification_url="https://geoflow.co.kr/signup/verify/"
        )

        self.assertTrue(
            signup_public_runtime_ready(
                settings_obj=settings_obj,
                environ={
                    "SITE_ORIGIN": "https://geoflow.co.kr",
                    "DEFAULT_FROM_EMAIL": "service@geoflow.co.kr",
                },
            )
        )
        outbox_config.assert_called_once()
        key_ring.assert_called_once()

    @patch("control.services.signup_runtime_readiness.load_signup_email_verification_key_ring")
    @patch("control.services.signup_runtime_readiness.load_signup_verification_outbox_config")
    def test_empty_environment_values_do_not_override_safe_settings(
        self,
        outbox_config,
        key_ring,
    ):
        settings_obj = SimpleNamespace(
            DEBUG=False,
            EMAIL_BACKEND=SMTP_BACKEND,
            EMAIL_HOST=NAVER_SMTP_HOST,
            EMAIL_PORT=NAVER_SMTP_PORT,
            EMAIL_USE_TLS=True,
            EMAIL_HOST_USER="configured-user",
            EMAIL_HOST_PASSWORD="configured-secret",
            DEFAULT_FROM_EMAIL="service@geoflow.co.kr",
            SITE_ORIGIN="https://geoflow.co.kr",
        )
        outbox_config.return_value = SimpleNamespace(
            verification_url="https://geoflow.co.kr/signup/verify/"
        )

        self.assertTrue(
            signup_public_runtime_ready(
                settings_obj=settings_obj,
                environ={"SITE_ORIGIN": " ", "DEFAULT_FROM_EMAIL": ""},
            )
        )
