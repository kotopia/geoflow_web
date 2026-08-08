from inspect import getsource
from pathlib import Path

from django.test import SimpleTestCase

from control.views_session import logout_view


class LogoutPostBoundaryTests(SimpleTestCase):
    def test_logout_view_is_post_only_and_csrf_protected(self):
        source = getsource(logout_view)
        self.assertIn("@require_POST", source)
        self.assertIn("@csrf_protect", source)

    def test_topbars_use_post_forms_with_csrf_tokens(self):
        root = Path(__file__).resolve().parents[1]
        templates = (
            root / "control/templates/control/partials/topbar.html",
            root / "geoflow_ops/templates/geoflow_ops/partials/topbar.html",
        )
        for template in templates:
            with self.subTest(template=template.name):
                source = template.read_text(encoding="utf-8")
                self.assertIn('method="post"', source)
                self.assertIn("{% csrf_token %}", source)
                self.assertNotIn(
                    '<a class="dropdown-item" href="{% url \'control:logout\' %}">Logout</a>',
                    source,
                )
