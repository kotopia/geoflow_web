from inspect import getsource
from pathlib import Path

from django.test import SimpleTestCase

from geoflow_ops.views_home_security import tenant_home


class TenantHomeBoundaryTests(SimpleTestCase):
    def test_tenant_home_requires_authenticated_current_tenant_context(self):
        source = getsource(tenant_home)
        self.assertIn("@login_required", source)
        self.assertIn("require_tenant_context(request)", source)
        self.assertIn('request.session.get("group_id")', source)

    def test_root_route_uses_guarded_home(self):
        urls_source = (
            Path(__file__).resolve().parent / "urls.py"
        ).read_text(encoding="utf-8")
        self.assertIn("from .views_home_security import tenant_home", urls_source)
        self.assertIn("path('', tenant_home, name='home')", urls_source)
        self.assertNotIn("path('', views.home, name='home')", urls_source)
