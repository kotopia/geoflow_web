import os
from contextlib import nullcontext
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from control.forms_signup import SignupRequestForm
from control.legal_policy import DEFAULT_PRIVACY_VERSION, DEFAULT_TERMS_VERSION
from control.services.signup_service import (
    PUBLIC_SIGNUP_ERROR,
    SignupRequestInput,
    SignupRequestReceipt,
    SignupRequestRejected,
    create_signup_request,
)


VALID_FORM = {
    "email": "Applicant@Example.com",
    "password": "a-long-uncommon-password-42!",
    "password_confirm": "a-long-uncommon-password-42!",
    "name_display": "신청자",
    "organization_name": "기관",
    "signup_purpose": "공간정보 업무 활용",
    "terms_agreed": "1",
    "privacy_agreed": "1",
}


class SignupRequestFormTests(SimpleTestCase):
    def test_valid_input_is_normalized_without_redisplaying_secrets(self):
        form = SignupRequestForm(VALID_FORM)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["email"], "applicant@example.com")

    def test_password_mismatch_fails_validation(self):
        values = {**VALID_FORM, "password_confirm": "different-password-42!"}
        form = SignupRequestForm(values)
        self.assertFalse(form.is_valid())
        self.assertIn("password_confirm", form.errors)

    def test_weak_password_fails_validation(self):
        values = {**VALID_FORM, "password": "123", "password_confirm": "123"}
        form = SignupRequestForm(values)
        self.assertFalse(form.is_valid())
        self.assertIn("password", form.errors)

    def test_initial_public_form_does_not_collect_deferred_optional_fields(self):
        form = SignupRequestForm()
        self.assertNotIn("contact_phone", form.fields)
        self.assertNotIn("invitation_code", form.fields)

    def test_terms_and_privacy_are_required(self):
        for field in ("terms_agreed", "privacy_agreed"):
            with self.subTest(field=field):
                values = {**VALID_FORM}
                values.pop(field)
                form = SignupRequestForm(values)
                self.assertFalse(form.is_valid())
                self.assertIn(field, form.errors)


@override_settings(SIGNUP_TERMS_VERSION="terms-test", SIGNUP_PRIVACY_VERSION="privacy-test")
class SignupRequestServiceTests(SimpleTestCase):
    def setUp(self):
        self.repository = MagicMock()
        self.repository.account_exists.return_value = False
        self.repository.create_inactive_user.return_value = "user-id"
        self.repository.create_signup_request.return_value = "request-id"
        self.data = SignupRequestInput(
            email="applicant@example.com",
            password="not-asserted-raw",
            name_display="신청자",
            contact_phone="",
            organization_name="기관",
            signup_purpose="업무 활용",
            terms_agreed=True,
            privacy_agreed=True,
        )

    @patch("control.services.signup_service.make_password", return_value="stored-hash")
    def test_valid_flow_creates_inactive_user_request_and_initial_event(self, mocked_hash):
        receipt = create_signup_request(
            self.data,
            repository=self.repository,
            atomic_context=nullcontext(),
        )

        input_repr = repr(self.data)
        for sensitive_value in (
            self.data.email,
            self.data.password,
            self.data.name_display,
            self.data.signup_purpose,
        ):
            self.assertNotIn(sensitive_value, input_repr)

        self.assertEqual(
            receipt,
            SignupRequestReceipt(
                user_id="user-id",
                signup_request_id="request-id",
            ),
        )
        self.assertNotIn("password", receipt.__dict__)
        self.assertNotIn("email", receipt.__dict__)
        self.assertNotIn(receipt.user_id, repr(receipt))
        self.assertNotIn(receipt.signup_request_id, repr(receipt))

        user_values = self.repository.create_inactive_user.call_args.kwargs
        self.assertIs(user_values["is_active"], False)
        self.assertIs(user_values["email_verified"], False)
        self.assertEqual(user_values["password_hash"], "stored-hash")

        request_values = self.repository.create_signup_request.call_args.kwargs
        self.assertNotIn("password", request_values)
        self.assertNotIn("password_hash", request_values)
        self.assertNotIn("token", request_values)
        self.assertNotIn("invitation_code", request_values)
        self.assertEqual(request_values["terms_version"], "terms-test")
        self.assertEqual(request_values["privacy_version"], "privacy-test")
        self.repository.append_submitted_event.assert_called_once()

    def test_existing_email_is_rejected_generically_without_writes(self):
        for account_case in ("active-account", "inactive-open-request"):
            with self.subTest(account_case=account_case):
                self.repository.reset_mock()
                self.repository.account_exists.return_value = True
                with self.assertRaisesMessage(SignupRequestRejected, PUBLIC_SIGNUP_ERROR):
                    create_signup_request(
                        self.data,
                        repository=self.repository,
                        atomic_context=nullcontext(),
                    )
                self.repository.create_inactive_user.assert_not_called()
                self.repository.create_signup_request.assert_not_called()
                self.repository.append_submitted_event.assert_not_called()

    def test_request_failure_prevents_event_and_uses_transaction_contract(self):
        atomic = MagicMock()
        atomic.__enter__.return_value = atomic
        atomic.__exit__.return_value = False
        self.repository.create_signup_request.side_effect = RuntimeError("test failure")

        with self.assertRaises(RuntimeError):
            create_signup_request(self.data, repository=self.repository, atomic_context=atomic)

        atomic.__enter__.assert_called_once()
        atomic.__exit__.assert_called_once()
        self.repository.append_submitted_event.assert_not_called()

    def test_invitation_input_cannot_trigger_membership_or_approval_writes(self):
        create_signup_request(self.data, repository=self.repository, atomic_context=nullcontext())
        called_methods = {call[0] for call in self.repository.method_calls}
        self.assertEqual(
            called_methods,
            {"account_exists", "create_inactive_user", "create_signup_request", "append_submitted_event"},
        )


class SignupLegalVersionFallbackTests(SimpleTestCase):
    def setUp(self):
        self.repository = MagicMock()
        self.repository.account_exists.return_value = False
        self.repository.create_inactive_user.return_value = "user-id"
        self.repository.create_signup_request.return_value = "request-id"
        self.data = SignupRequestInput(
            email="applicant@example.com",
            password="not-asserted-raw",
            name_display="신청자",
            contact_phone="",
            organization_name="기관",
            signup_purpose="업무 활용",
            terms_agreed=True,
            privacy_agreed=True,
        )

    @override_settings(SIGNUP_TERMS_VERSION="", SIGNUP_PRIVACY_VERSION="")
    @patch.dict(
        os.environ,
        {"SIGNUP_TERMS_VERSION": "", "SIGNUP_PRIVACY_VERSION": ""},
        clear=False,
    )
    @patch("control.services.signup_service.make_password", return_value="stored-hash")
    def test_final_display_versions_are_the_signup_record_fallbacks(self, mocked_hash):
        create_signup_request(
            self.data,
            repository=self.repository,
            atomic_context=nullcontext(),
        )

        request_values = self.repository.create_signup_request.call_args.kwargs
        self.assertEqual(request_values["terms_version"], DEFAULT_TERMS_VERSION)
        self.assertEqual(request_values["privacy_version"], DEFAULT_PRIVACY_VERSION)
