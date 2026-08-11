from types import SimpleNamespace
import unittest

from django.conf import settings

if not settings.configured:
    settings.configure(DEFAULT_CHARSET="utf-8", SECRET_KEY="authz-contract-test")

from django.http import HttpResponse

from control.gf_authz.permissions import (
    gf_get_perms,
    gf_get_roles,
    gf_has_perm,
    gf_has_role,
    gf_perm_required,
)


class Request:
    def __init__(self, *, authenticated=True, session=None):
        self.user = SimpleNamespace(is_authenticated=authenticated)
        self.session = {} if session is None else session


class AuthorizationPermissionContractTests(unittest.TestCase):
    def test_anonymous_request_is_denied(self):
        request = Request(authenticated=False)
        request._gf_perms_cache = {"projects.view"}
        request._gf_roles_cache = {"OWNER"}

        self.assertFalse(gf_has_perm(request, "projects.view"))
        self.assertFalse(gf_has_role(request, "OWNER"))

    def test_request_permission_and_role_caches_are_canonical(self):
        request = Request()
        request._gf_perms_cache = {"projects.view"}
        request._gf_roles_cache = {"viewer"}

        self.assertEqual(gf_get_perms(request), {"projects.view"})
        self.assertEqual(gf_get_roles(request), {"viewer"})
        self.assertTrue(gf_has_perm(request, "projects.view"))
        self.assertTrue(gf_has_role(request, "viewer"))
        self.assertFalse(gf_has_perm(request, "projects.edit"))

    def test_roles_do_not_implicitly_expand_permissions(self):
        request = Request()
        request._gf_perms_cache = set()
        request._gf_roles_cache = {"OWNER", "ADMIN"}

        self.assertFalse(gf_has_perm(request, "projects.edit"))
        self.assertTrue(gf_has_role(request, "OWNER"))
        self.assertTrue(gf_has_role(request, "ADMIN"))

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

        self.assertEqual(gf_get_perms(request), set())
        self.assertEqual(gf_get_roles(request), set())
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

    def test_permission_decorator_preserves_or_contract(self):
        @gf_perm_required("projects.edit", "projects.view", redirect_to_login=False)
        def protected(request):
            return HttpResponse("ok")

        allowed = Request()
        allowed._gf_perms_cache = {"projects.view"}
        denied = Request()
        denied._gf_perms_cache = {"directory.view"}
        empty = Request()
        empty._gf_perms_cache = set()

        self.assertEqual(protected(allowed).status_code, 200)
        self.assertEqual(protected(denied).status_code, 403)
        self.assertEqual(protected(empty).status_code, 403)

    def test_blank_codes_are_denied(self):
        request = Request()
        request._gf_perms_cache = {"projects.view"}
        request._gf_roles_cache = {"viewer"}

        self.assertFalse(gf_has_perm(request, ""))
        self.assertFalse(gf_has_role(request, ""))


if __name__ == "__main__":
    unittest.main()
