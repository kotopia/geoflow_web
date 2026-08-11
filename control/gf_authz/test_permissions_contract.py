from types import SimpleNamespace
import unittest

from control.gf_authz.permissions import gf_has_perm, gf_has_role


class Request:
    def __init__(self, *, authenticated=True, superuser=False, session=None):
        self.user = SimpleNamespace(
            is_authenticated=authenticated,
            is_superuser=superuser,
        )
        self.session = {} if session is None else session


class AuthorizationPermissionContractTests(unittest.TestCase):
    def test_anonymous_request_is_denied(self):
        request = Request(authenticated=False)
        request._gf_perms_cache = {"projects.view"}
        request._gf_roles_cache = {"OWNER"}

        self.assertFalse(gf_has_perm(request, "projects.view"))
        self.assertFalse(gf_has_role(request, "OWNER"))

    def test_request_permission_cache_is_canonical(self):
        request = Request()
        request._gf_perms_cache = {"projects.view"}
        request._gf_roles_cache = set()

        self.assertTrue(gf_has_perm(request, "projects.view"))
        self.assertFalse(gf_has_perm(request, "projects.edit"))

    def test_superuser_and_existing_privileged_roles_keep_bypass(self):
        superuser = Request(superuser=True)
        self.assertTrue(gf_has_perm(superuser, "anything"))
        self.assertTrue(gf_has_role(superuser, "anything"))

        for role in ("OWNER", "ADMIN"):
            with self.subTest(role=role):
                request = Request()
                request._gf_perms_cache = set()
                request._gf_roles_cache = {role}
                self.assertTrue(gf_has_perm(request, "projects.edit"))

    def test_missing_context_fails_closed(self):
        request = Request()

        self.assertFalse(gf_has_perm(request, "projects.view"))
        self.assertFalse(gf_has_role(request, "OWNER"))

    def test_empty_request_cache_does_not_reuse_stale_session_permissions(self):
        request = Request(
            session={
                "gf_perms": ["projects.edit"],
                "gf_roles": ["OWNER"],
            }
        )
        request._gf_perms_cache = set()
        request._gf_roles_cache = set()

        self.assertFalse(gf_has_perm(request, "projects.edit"))
        self.assertFalse(gf_has_role(request, "OWNER"))

    def test_session_cache_is_only_fallback_when_request_cache_is_absent(self):
        request = Request(
            session={
                "gf_perms": ["directory.view"],
                "gf_roles": ["viewer"],
            }
        )

        self.assertTrue(gf_has_perm(request, "directory.view"))
        self.assertTrue(gf_has_role(request, "viewer"))
        self.assertFalse(gf_has_perm(request, "directory.edit"))

    def test_blank_codes_are_denied(self):
        request = Request(superuser=True)

        self.assertFalse(gf_has_perm(request, ""))
        self.assertFalse(gf_has_role(request, ""))


if __name__ == "__main__":
    unittest.main()
