from contextlib import nullcontext
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from control.services.signup_service import (
    PUBLIC_SIGNUP_ERROR,
    SignupRequestInput,
    SignupRequestRejected,
    create_signup_request,
)


class SignupEnumerationTimingHardeningTests(SimpleTestCase):
    def setUp(self):
        self.data = SignupRequestInput(
            email="applicant@example.com",
            password="candidate-password-value",
            name_display="신청자",
            contact_phone="",
            organization_name="기관",
            signup_purpose="업무 활용",
            terms_agreed=True,
            privacy_agreed=True,
        )
        self.repository = MagicMock()
        self.repository.account_exists.return_value = False
        self.repository.create_inactive_user.return_value = "user-reference"
        self.repository.create_signup_request.return_value = "request-reference"

    @patch(
        "control.services.signup_service.make_password",
        return_value="computed-password-hash",
    )
    def test_existing_account_still_pays_password_hash_cost(self, make_password):
        self.repository.account_exists.return_value = True

        with self.assertRaisesMessage(SignupRequestRejected, PUBLIC_SIGNUP_ERROR):
            create_signup_request(
                self.data,
                repository=self.repository,
                atomic_context=nullcontext(),
            )

        make_password.assert_called_once_with(self.data.password)
        self.repository.account_exists.assert_called_once_with(self.data.email)
        self.repository.create_inactive_user.assert_not_called()
        self.repository.create_signup_request.assert_not_called()
        self.repository.append_submitted_event.assert_not_called()

    @patch(
        "control.services.signup_service.make_password",
        return_value="computed-password-hash",
    )
    def test_new_account_reuses_precomputed_hash_for_single_hash_cost(
        self,
        make_password,
    ):
        create_signup_request(
            self.data,
            repository=self.repository,
            atomic_context=nullcontext(),
        )

        make_password.assert_called_once_with(self.data.password)
        created = self.repository.create_inactive_user.call_args.kwargs
        self.assertEqual(created["password_hash"], "computed-password-hash")
        self.assertNotEqual(created["password_hash"], self.data.password)

    def test_public_rejection_message_does_not_disclose_account_state(self):
        normalized = PUBLIC_SIGNUP_ERROR.lower()
        for forbidden in (
            "이미 가입",
            "존재하는",
            "비활성",
            "pending",
            "approved",
        ):
            self.assertNotIn(forbidden, normalized)
