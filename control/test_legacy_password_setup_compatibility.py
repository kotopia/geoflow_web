from inspect import getsource
from unittest import TestCase
from unittest.mock import MagicMock

from control.services.legacy_password_setup_compatibility import (
    CentralLegacyPasswordSetupCompatibilityRepository,
    LegacyPasswordSetupSignupConflict,
    require_legacy_password_setup_compatible,
)


class LegacyPasswordSetupCompatibilityTests(TestCase):
    def setUp(self):
        self.repository = MagicMock()
        self.repository.has_open_signup_request.return_value = False

    def test_non_signup_user_keeps_legacy_password_setup_available(self):
        require_legacy_password_setup_compatible(
            " user-reference ",
            repository=self.repository,
        )

        self.repository.has_open_signup_request.assert_called_once_with(
            user_id="user-reference"
        )

    def test_open_signup_request_is_blocked_without_followup_write_contract(self):
        self.repository.has_open_signup_request.return_value = True

        with self.assertRaises(LegacyPasswordSetupSignupConflict):
            require_legacy_password_setup_compatible(
                "user-reference",
                repository=self.repository,
            )

    def test_empty_user_identifier_fails_before_repository_read(self):
        with self.assertRaises(ValueError):
            require_legacy_password_setup_compatible(
                " ",
                repository=self.repository,
            )

        self.repository.has_open_signup_request.assert_not_called()

    def test_repository_checks_only_open_signup_states_in_central_table(self):
        source = getsource(
            CentralLegacyPasswordSetupCompatibilityRepository.has_open_signup_request
        )

        self.assertIn("FROM signup_requests", source)
        self.assertIn("'pending_email_verification'", source)
        self.assertIn("'pending_approval'", source)
        for forbidden in (
            "UPDATE ",
            "DELETE ",
            "INSERT ",
            "join_requests",
            "user_group_map",
            "employee_profile",
            "password_hash",
        ):
            self.assertNotIn(forbidden, source)
