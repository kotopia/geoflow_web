from inspect import getsource
from unittest import TestCase

from control.services.signup_submission_runtime import (
    submit_signup_with_email_verification,
)
from control.services.signup_verification_delivery import (
    build_signup_email_verification_link,
)
from control.services.signup_verification_email_delivery import (
    send_signup_email_verification_email,
)
from control.services.signup_verification_resend_service import (
    prepare_signup_email_verification_resend,
)
from control.services.signup_verification_runtime import (
    load_signup_email_verification_key_ring,
    verify_signup_email_from_runtime_config,
)
from control.services.signup_verification_service import verify_signup_email
from control.services.signup_verification_token_service import (
    DatabaseSignupEmailVerificationTokenVerifier,
    issue_signup_email_verification_token,
    verify_signup_email_with_database_token,
)


class SignupSensitiveExceptionFrameTests(TestCase):
    def test_token_and_delivery_boundaries_mark_sensitive_local_variables(self):
        contracts = (
            (build_signup_email_verification_link, 'sensitive_variables("token")'),
            (verify_signup_email, 'sensitive_variables("token")'),
            (
                verify_signup_email_from_runtime_config,
                'sensitive_variables("token", "key_ring")',
            ),
            (
                verify_signup_email_with_database_token,
                'sensitive_variables("token", "key_ring")',
            ),
            (
                issue_signup_email_verification_token,
                'sensitive_variables("key_ring", "secret", "token")',
            ),
            (prepare_signup_email_verification_resend, 'sensitive_variables('),
            (send_signup_email_verification_email, 'sensitive_variables('),
            (submit_signup_with_email_verification, 'sensitive_variables('),
        )
        for callable_obj, marker in contracts:
            with self.subTest(callable_obj=callable_obj.__name__):
                self.assertIn(marker, getsource(callable_obj))

    def test_key_loader_marks_decoded_key_material_sensitive(self):
        source = getsource(load_signup_email_verification_key_ring)

        for variable in (
            "configured_keys",
            "decoded_keys",
            "encoded_key",
        ):
            self.assertIn(variable, source)
        self.assertIn("sensitive_variables", source)

    def test_database_verifier_consume_marks_raw_token_sensitive(self):
        source = getsource(DatabaseSignupEmailVerificationTokenVerifier.consume)

        self.assertIn('sensitive_variables("token")', source)
