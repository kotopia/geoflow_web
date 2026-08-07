from pathlib import Path
from unittest import TestCase


CONTROL_DIR = Path(__file__).resolve().parent


class SignupActivationSafetyContractTests(TestCase):
    def test_public_signup_fails_closed_when_outbox_is_disabled(self):
        source = (CONTROL_DIR / "views_signup.py").read_text(encoding="utf-8")

        self.assertIn("signup_verification_outbox_enabled()", source)
        self.assertIn("and signup_terms_url", source)
        self.assertIn("and signup_privacy_url", source)
        self.assertIn("if not signup_available:", source)
        self.assertIn("SIGNUP_UNAVAILABLE_MESSAGE", source)
        self.assertNotIn("create_signup_request(signup_data)", source)
        self.assertIn("create_signup_request_with_verification_outbox(signup_data)", source)

    def test_disabled_signup_returns_service_unavailable_and_does_not_hide_verify_route(self):
        source = (CONTROL_DIR / "views_signup.py").read_text(encoding="utf-8")

        self.assertIn("status=200 if signup_available else 503", source)
        self.assertIn("def signup_email_verification_view(request):", source)

    def test_signup_template_hides_form_while_disabled(self):
        source = (
            CONTROL_DIR / "templates/control/signup.html"
        ).read_text(encoding="utf-8")

        self.assertIn("{% if not signup_available %}", source)
        self.assertIn("{% else %}", source)
        self.assertIn("<form method=\"post\"", source)

    def test_legal_documents_can_be_linked_without_rel_opener(self):
        source = (
            CONTROL_DIR / "templates/control/signup.html"
        ).read_text(encoding="utf-8")

        self.assertIn("signup_terms_url", source)
        self.assertIn("signup_privacy_url", source)
        view_source = (CONTROL_DIR / "views_signup.py").read_text(encoding="utf-8")
        self.assertIn("def _public_document_url", view_source)
        self.assertIn("os.environ.get(setting_name)", view_source)
        self.assertGreaterEqual(source.count('rel="noopener noreferrer"'), 2)
    def test_legal_document_versions_can_be_rotated_from_environment(self):
        source = (
            CONTROL_DIR / "services/signup_service.py"
        ).read_text(encoding="utf-8")

        self.assertIn('os.environ.get(name)', source)
        self.assertIn('"SIGNUP_TERMS_VERSION"', source)
        self.assertIn('"SIGNUP_PRIVACY_VERSION"', source)
        self.assertIn('default="phase1-v1"', source)
