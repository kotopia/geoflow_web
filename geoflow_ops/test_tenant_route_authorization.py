from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent


class TenantRouteAuthorizationStaticTests(unittest.TestCase):
    def test_sensitive_routes_are_wrapped(self):
        urls = (ROOT / "urls.py").read_text(encoding="utf-8")
        for route in (
            "security_views.contract_json",
            "security_views.partner_detail",
            "security_views.partner_json",
            "security_views.catalog_board",
            "security_views.project_list",
            "security_views.project_detail",
            "security_views.orgunit_list",
            "security_views.orgunit_create",
            "security_views.orgunit_detail",
            "security_views.orgunit_update",
            "security_views.event_modal_ui",
        ):
            self.assertIn(route, urls)
        self.assertNotIn('path("projects/", views_projects.ProjectListView.as_view()', urls)

    def test_get_post_permission_parity(self):
        source = (ROOT / "security_views.py").read_text(encoding="utf-8")
        self.assertIn('_require(request, "projects.view")', source)
        self.assertIn('request.method == "POST" and not gf_has_perm(request, "projects.edit")', source)
        self.assertIn('_require(request, "contracts.view")', source)
        self.assertIn('_require(request, "partners.view")', source)
        self.assertIn('request.method == "POST" and not gf_has_perm(request, "partners.create")', source)
        self.assertIn('_require(request, "directory.view")', source)
        self.assertIn('_require(request, "directory.edit")', source)

    def test_event_modal_is_scope_authorized(self):
        source = (ROOT / "security_views.py").read_text(encoding="utf-8")
        self.assertIn("alias = require_tenant_context(request)", source)
        self.assertIn("authorize_scope_read(request, alias, scope_type, scope_id)", source)


if __name__ == "__main__":
    unittest.main()
