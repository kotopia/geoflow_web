from inspect import getsource
from unittest import TestCase

from control.views_signup import _public_document_url


class SignupPublicHttpsBoundaryTests(TestCase):
    def test_non_debug_public_documents_require_https(self):
        source = getsource(_public_document_url)
        self.assertIn('not getattr(settings, "DEBUG", False)', source)
        self.assertIn('parts.scheme != "https"', source)

    def test_public_signup_and_resend_restrict_methods(self):
        source = (
            __import__("pathlib").Path(__file__).resolve().parent / "views_signup.py"
        ).read_text(encoding="utf-8")
        self.assertGreaterEqual(
            source.count('@require_http_methods(["GET", "POST"])'),
            3,
        )

    def test_signup_gate_requires_current_code_legal_versions(self):
        source = (
            __import__("pathlib").Path(__file__).resolve().parent / "views_signup.py"
        ).read_text(encoding="utf-8")
        self.assertIn("_legal_versions_current()", source)
        self.assertIn("== DEFAULT_TERMS_VERSION", source)
        self.assertIn("== DEFAULT_PRIVACY_VERSION", source)

    def test_public_legal_urls_are_same_origin_and_canonical_paths(self):
        source = getsource(_public_document_url)
        self.assertIn('"SIGNUP_TERMS_URL": "/terms/"', source)
        self.assertIn('"SIGNUP_PRIVACY_URL": "/privacy/"', source)
        self.assertIn("SITE_ORIGIN", source)
        self.assertIn("parts.query", source)
        self.assertIn("parts.fragment", source)

