from inspect import getsource

from django.test import SimpleTestCase

from control import views_groups_admin


class CentralGroupAdminBoundaryTests(SimpleTestCase):
    def test_dormant_unprotected_group_switch_helper_is_removed(self):
        self.assertFalse(hasattr(views_groups_admin, "group_select"))
        self.assertFalse(
            hasattr(views_groups_admin, "_resolve_tenant_alias_by_group")
        )

    def test_group_mutation_views_are_central_admin_csrf_get_post_only(self):
        for view in (
            views_groups_admin.group_create_admin,
            views_groups_admin.group_edit_admin,
        ):
            with self.subTest(view=view.__name__):
                source = getsource(view)
                self.assertIn("@require_central_admin", source)
                self.assertIn("@csrf_protect", source)
                self.assertIn('@require_http_methods(["GET", "POST"])', source)

    def test_group_edit_status_is_server_allowlisted(self):
        source = getsource(views_groups_admin.group_edit_admin)
        self.assertIn("if status not in STATUS_CHOICES", source)
