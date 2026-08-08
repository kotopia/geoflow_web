from inspect import getsource
from pathlib import Path

from django.test import SimpleTestCase

from control.views_groups import group_search_view, group_select_view


class GroupSelectionBoundaryTests(SimpleTestCase):
    def test_group_search_requires_authenticated_get(self):
        source = getsource(group_search_view)
        self.assertIn("@login_required", source)
        self.assertIn("@require_GET", source)

    def test_group_selection_requires_authenticated_csrf_post(self):
        source = getsource(group_select_view)
        self.assertIn("@login_required", source)
        self.assertIn("@require_POST", source)
        self.assertIn("@csrf_protect", source)

    def test_group_selection_template_posts_with_csrf(self):
        template = (
            Path(__file__).resolve().parent
            / "templates/control/group_search.html"
        ).read_text(encoding="utf-8")
        self.assertIn('method="post"', template)
        self.assertIn("{% csrf_token %}", template)
        self.assertNotIn('href="{% url \'control:group_select\'', template)
