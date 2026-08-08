from inspect import getsource

from django.test import SimpleTestCase

from geoflow_ops import security_views


class TenantSecurityMethodBoundaryTests(SimpleTestCase):
    def test_read_wrappers_are_get_only(self):
        for view in (
            security_views.project_list,
            security_views.contract_json,
            security_views.partner_json,
            security_views.catalog_board,
            security_views.project_scope_modal,
            security_views.project_scope_data,
            security_views.project_scope_summary,
            security_views.orgunit_list,
            security_views.orgunit_detail,
            security_views.event_modal_ui,
        ):
            with self.subTest(view=view.__name__):
                self.assertIn("@require_GET", getsource(view))

    def test_form_wrappers_allow_only_get_and_post(self):
        for view in (
            security_views.project_detail,
            security_views.partner_detail,
            security_views.orgunit_create,
            security_views.orgunit_update,
        ):
            with self.subTest(view=view.__name__):
                self.assertIn(
                    '@require_http_methods(["GET", "POST"])',
                    getsource(view),
                )

    def test_scope_save_is_post_only(self):
        self.assertIn("@require_POST", getsource(security_views.project_scope_save))
