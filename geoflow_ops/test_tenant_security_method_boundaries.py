from inspect import getsource

from django.test import SimpleTestCase

from geoflow_ops import security_views


class TenantSecurityMethodBoundaryTests(SimpleTestCase):
    def test_read_wrappers_are_get_only(self):
        for view in (
            security_views.contract_list,
            security_views.contract_json,
            security_views.partner_list,
            security_views.partner_json,
            security_views.partner_options,
            security_views.project_list,
            security_views.project_json,
            security_views.project_summary,
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
            security_views.contract_create,
            security_views.contract_detail,
            security_views.partner_create,
            security_views.partner_detail,
            security_views.project_detail,
            security_views.orgunit_create,
            security_views.orgunit_update,
        ):
            with self.subTest(view=view.__name__):
                self.assertIn(
                    '@require_http_methods(["GET", "POST"])',
                    getsource(view),
                )

    def test_mutating_project_wrappers_are_post_only(self):
        for view in (
            security_views.project_scope_save,
            security_views.project_summary_save,
        ):
            with self.subTest(view=view.__name__):
                self.assertIn("@require_POST", getsource(view))

    def test_write_permission_split_is_explicit(self):
        self.assertIn(
            'gf_has_perm(request, "contracts.edit")',
            getsource(security_views.contract_detail),
        )
        self.assertIn(
            'gf_has_perm(request, "partners.create")',
            getsource(security_views.partner_detail),
        )
