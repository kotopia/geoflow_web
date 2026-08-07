from pathlib import Path
from unittest import TestCase

CONTROL_DIR = Path(__file__).resolve().parent


class SignupReviewAdminRouteContractTests(TestCase):
    def test_urlconf_exposes_only_named_signup_review_admin_routes(self):
        source = (CONTROL_DIR / "urls.py").read_text(encoding="utf-8")
        for route_name in (
            "signup_reviews_admin",
            "signup_review_detail_admin",
            "signup_review_decide_admin",
        ):
            self.assertIn(route_name, source)
        self.assertIn('"mgmt/signup-reviews/"', source)

    def test_review_views_require_central_admin_and_correct_http_methods(self):
        source = (CONTROL_DIR / "views_signup_admin.py").read_text(
            encoding="utf-8"
        )
        self.assertEqual(source.count("@require_central_admin"), 3)
        self.assertEqual(source.count("@never_cache"), 2)
        self.assertEqual(source.count("@require_GET"), 2)
        self.assertEqual(source.count("@require_POST"), 1)

    def test_decision_note_is_masked_and_service_delegation_is_explicit(self):
        source = (CONTROL_DIR / "views_signup_admin.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('@sensitive_post_parameters("note")', source)
        self.assertIn('@sensitive_variables("note")', source)
        self.assertIn("list_pending_signup_reviews", source)
        self.assertIn("get_pending_signup_review", source)
        self.assertIn("decide_signup_account", source)
        self.assertIn("SignupAccountDecision", source)

    def test_admin_controller_does_not_write_membership_state(self):
        source = (CONTROL_DIR / "views_signup_admin.py").read_text(
            encoding="utf-8"
        ).lower()
        self.assertNotIn("user_group_map", source)
        self.assertNotIn("membership", source)
        self.assertNotIn("tenant_repo", source)

    def test_detail_form_posts_version_note_and_both_decisions_with_csrf(self):
        source = (
            CONTROL_DIR / "templates/control/signup_review_detail_admin.html"
        ).read_text(encoding="utf-8")
        self.assertEqual(source.count("{% csrf_token %}"), 1)
        self.assertIn('name="version"', source)
        self.assertIn('name="note"', source)
        self.assertIn("'approve'", source)
        self.assertIn("'reject'", source)
        self.assertIn("terms_accepted_at", source)
        self.assertIn("privacy_accepted_at", source)

    def test_sidebar_exposes_signup_reviews_only_to_central_staff(self):
        source = (
            CONTROL_DIR / "templates/control/partials/sidebar.html"
        ).read_text(encoding="utf-8")
        staff_guard = source.index("{% if central_is_staff %}")
        review_link = source.index("control:signup_reviews_admin")
        staff_end = source.index("{% endif %}", staff_guard)
        self.assertLess(staff_guard, review_link)
        self.assertLess(review_link, staff_end)
