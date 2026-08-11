import unittest
from types import SimpleNamespace

from control.gf_authz.services import _resolve_request_identity


class GFAuthzBridgeIdentityTests(unittest.TestCase):
    def _request(self, *, email=None, username=None):
        return SimpleNamespace(user=SimpleNamespace(email=email, username=username))

    def test_prefers_normalized_email_when_present(self):
        request = self._request(
            email="  Tenant.Admin@Example.COM  ",
            username="different@example.com",
        )
        self.assertEqual(
            _resolve_request_identity(request),
            "tenant.admin@example.com",
        )

    def test_falls_back_to_legacy_bridge_username_when_email_is_blank(self):
        request = self._request(
            email="",
            username="  Legacy.User@Example.COM  ",
        )
        self.assertEqual(
            _resolve_request_identity(request),
            "legacy.user@example.com",
        )

    def test_missing_bridge_identity_fails_closed_to_empty_string(self):
        request = self._request(email=None, username=None)
        self.assertEqual(_resolve_request_identity(request), "")

    def test_missing_user_fails_closed_to_empty_string(self):
        request = SimpleNamespace()
        self.assertEqual(_resolve_request_identity(request), "")


if __name__ == "__main__":
    unittest.main()
