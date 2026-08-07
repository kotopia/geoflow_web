from types import SimpleNamespace
from unittest import TestCase

from control.services.signup_verification_outbox_feature import (
    signup_verification_outbox_enabled,
)


class SignupVerificationOutboxFeatureTests(TestCase):
    def test_feature_defaults_disabled(self):
        self.assertFalse(
            signup_verification_outbox_enabled(
                settings_obj=SimpleNamespace(),
                environ={},
            )
        )

    def test_explicit_boolean_setting_has_precedence(self):
        self.assertTrue(
            signup_verification_outbox_enabled(
                settings_obj=SimpleNamespace(
                    ENABLE_SIGNUP_EMAIL_VERIFICATION_OUTBOX=True,
                ),
                environ={"ENABLE_SIGNUP_EMAIL_VERIFICATION_OUTBOX": "0"},
            )
        )
        self.assertFalse(
            signup_verification_outbox_enabled(
                settings_obj=SimpleNamespace(
                    ENABLE_SIGNUP_EMAIL_VERIFICATION_OUTBOX=False,
                ),
                environ={"ENABLE_SIGNUP_EMAIL_VERIFICATION_OUTBOX": "1"},
            )
        )

    def test_environment_can_enable_when_setting_is_absent(self):
        self.assertTrue(
            signup_verification_outbox_enabled(
                settings_obj=SimpleNamespace(),
                environ={"ENABLE_SIGNUP_EMAIL_VERIFICATION_OUTBOX": "true"},
            )
        )

    def test_invalid_environment_value_fails_closed(self):
        self.assertFalse(
            signup_verification_outbox_enabled(
                settings_obj=SimpleNamespace(),
                environ={"ENABLE_SIGNUP_EMAIL_VERIFICATION_OUTBOX": "maybe"},
            )
        )
