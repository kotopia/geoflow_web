from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from control.services.central_login_authentication import (
    PUBLIC_LOGIN_ERROR,
    CentralLoginPasswordConfigurationError,
    burn_central_login_password_check,
    verify_central_login_password,
)


class CentralLoginAuthenticationTests(TestCase):
    def test_public_error_is_generic(self):
        normalized = PUBLIC_LOGIN_ERROR.lower()
        self.assertIn("이메일", normalized)
        self.assertIn("비밀번호", normalized)
        self.assertNotIn("사용자를 찾을 수", normalized)
        self.assertNotIn("비활성", normalized)

    @patch("control.services.central_login_authentication.check_password")
    def test_missing_hash_burns_dummy_check_and_rejects(self, check_password):
        result = verify_central_login_password("candidate", None)

        self.assertFalse(result.valid)
        self.assertFalse(result.needs_rehash)
        check_password.assert_called_once()
        self.assertEqual(check_password.call_args.args[0], "candidate")

    @patch("control.services.central_login_authentication.check_password")
    def test_dummy_check_does_not_return_a_result(self, check_password):
        self.assertIsNone(burn_central_login_password_check("candidate"))
        check_password.assert_called_once()

    @patch("control.services.central_login_authentication.identify_hasher")
    @patch("control.services.central_login_authentication.check_password")
    def test_pbkdf2_success_does_not_request_rehash(
        self, check_password, identify_hasher
    ):
        check_password.return_value = True
        identify_hasher.return_value = SimpleNamespace(algorithm="pbkdf2_sha256")

        result = verify_central_login_password("candidate", "pbkdf2_sha256$encoded")

        self.assertTrue(result.valid)
        self.assertFalse(result.needs_rehash)

    @patch("control.services.central_login_authentication.identify_hasher")
    @patch("control.services.central_login_authentication.check_password")
    def test_non_pbkdf2_success_requests_rehash(
        self, check_password, identify_hasher
    ):
        check_password.return_value = True
        identify_hasher.return_value = SimpleNamespace(algorithm="argon2")

        result = verify_central_login_password("candidate", "argon2$encoded")

        self.assertTrue(result.valid)
        self.assertTrue(result.needs_rehash)

    @patch("control.services.central_login_authentication.check_password")
    def test_invalid_password_is_generic_failure(self, check_password):
        check_password.return_value = False

        result = verify_central_login_password(
            "candidate", "pbkdf2_sha256$encoded"
        )

        self.assertFalse(result.valid)
        self.assertFalse(result.needs_rehash)

    @patch("builtins.__import__", side_effect=ImportError)
    def test_missing_bcrypt_is_internal_configuration_error(self, _import):
        with self.assertRaises(CentralLoginPasswordConfigurationError):
            verify_central_login_password("candidate", "$2b$legacy")
